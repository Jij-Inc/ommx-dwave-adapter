import copy
import os
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import dimod

if __package__:
    from . import instance as benchmark_instances
else:
    import instance as benchmark_instances
from ommx import Instance

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter

INSTANCE_BUILDERS = {
    "knapsack": benchmark_instances.build_knapsack_instance,
    "production": benchmark_instances.build_production_instance,
    "blending": benchmark_instances.build_blending_instance,
    "assignment": benchmark_instances.build_assignment_instance,
    "facility-location": benchmark_instances.build_facility_location_instance,
    "portfolio": benchmark_instances.build_portfolio_instance,
    "portfolio-cardinality": benchmark_instances.build_portfolio_cardinality_instance,
    "unit-commitment": benchmark_instances.build_unit_commitment_instance,
    "clique": benchmark_instances.build_clique_instance,
    "tsp": benchmark_instances.build_tsp_instance,
}
PREPARATION_INSTANCE_NAME = "one-hot-preparation"
INSTANCE_NAMES = (*INSTANCE_BUILDERS, PREPARATION_INSTANCE_NAME)
FORMULATIONS = ("regular", "one-hot")
SPECIAL_CONSTRAINT_CASES = ("none", "indicator", "sos1", "indicator-sos1")
PREPARATIONS = ("none", "recommended")
OPERATIONS = (
    "prepare",
    "instance-to-model",
    "result-to-solution",
    "end-to-end",
)

PACKAGE_VERSIONS = (
    version("ommx"),
    version("dimod"),
    version("dwave-system"),
    version("ommx_dwave_adapter"),
)


@dataclass(frozen=True)
class BenchmarkOperation:
    """Separate per-sample setup from the operation being measured."""

    setup: Callable[[], Any]
    run: Callable[[Any], Any]


def build_instance(
    name: str,
    size: int,
    seed: int,
    formulation: str,
    special_constraints: str = "none",
    preparation: str = "none",
) -> Instance:
    """Select and build a benchmark Instance."""
    if name == PREPARATION_INSTANCE_NAME:
        return benchmark_instances.build_one_hot_preparation_instance(
            size,
            seed,
            formulation,
            special_constraints,
            preparation,
        )
    if special_constraints != "none":
        raise ValueError(
            "Special constraints are available only for one-hot-preparation"
        )
    if preparation != "none":
        raise ValueError(
            "Preparation is available only for one-hot-preparation special constraints"
        )
    return INSTANCE_BUILDERS[name](size, seed, formulation)


def _prepare_instance(instance: Instance) -> Instance:
    input_class = OMMXLeapHybridCQMAdapter.INPUT_CLASS
    if input_class is None:
        raise RuntimeError("The adapter does not declare INPUT_CLASS")
    prepared = copy.copy(instance)
    prepared.prepare(
        input_class,
        OMMXLeapHybridCQMAdapter.recommended_preparation_policy(),
    )
    return prepared


def _build_feasible_sample(
    name: str, size: int, model: dimod.ConstrainedQuadraticModel
) -> dict[int, float]:
    """Build a deterministic feasible sample for a benchmark model."""
    sample = {variable: 0.0 for variable in model.variables}

    if name == "blending":
        sample.update({variable: 1.0 for variable in model.variables})
    elif name == PREPARATION_INSTANCE_NAME:
        sample.update({group * size: 1.0 for group in range(size)})
    elif name in ("assignment", "tsp"):
        sample.update({index * size + index: 1.0 for index in range(size)})
    elif name == "unit-commitment":
        sample.update({generator: 1.0 for generator in range(size)})
        sample.update({size + generator: 5.0 for generator in range(size)})
    elif name == "clique":
        clique_size = (size + 1) // 2
        sample.update({vertex: 1.0 for vertex in range(size - clique_size, size)})

    return sample


def make_benchmark_operation(
    operation: str,
    instance: Instance,
    name: str,
    size: int,
    solver_time_limit_s: int,
    special_constraints: str,
    preparation: str,
) -> BenchmarkOperation:
    """Prepare setup and the measured call for a benchmark operation."""
    if operation == "prepare":
        if special_constraints == "none" or preparation != "recommended":
            raise ValueError(
                "prepare requires Indicator and/or SOS1 constraints with "
                "recommended preparation"
            )
        input_class = OMMXLeapHybridCQMAdapter.INPUT_CLASS
        if input_class is None:
            raise RuntimeError("The adapter does not declare INPUT_CLASS")

        def setup_preparation() -> tuple[Instance, Any]:
            return (
                copy.copy(instance),
                OMMXLeapHybridCQMAdapter.recommended_preparation_policy(),
            )

        def run_preparation(context: tuple[Instance, Any]) -> Instance:
            prepared, policy = context
            prepared.prepare(input_class, policy)
            return prepared

        return BenchmarkOperation(setup=setup_preparation, run=run_preparation)

    if operation == "end-to-end":
        token = os.environ.get("DWAVE_API_TOKEN")
        if not token:
            raise RuntimeError("DWAVE_API_TOKEN is required")
        if preparation == "recommended":
            return BenchmarkOperation(
                setup=lambda: instance,
                run=lambda target: OMMXLeapHybridCQMAdapter.solve(
                    target,
                    token=token,
                    time_limit=solver_time_limit_s,
                ),
            )
        return BenchmarkOperation(
            setup=lambda: instance,
            run=lambda target: OMMXLeapHybridCQMAdapter.solve_without_preparation(
                target,
                token=token,
                time_limit=solver_time_limit_s,
            ),
        )

    adapter_instance = (
        _prepare_instance(instance) if preparation == "recommended" else instance
    )
    if operation == "instance-to-model":
        return BenchmarkOperation(
            setup=lambda: adapter_instance,
            run=lambda target: OMMXLeapHybridCQMAdapter(target).solver_input,
        )

    if operation != "result-to-solution":
        raise ValueError(f"Unknown operation: {operation}")

    adapter = OMMXLeapHybridCQMAdapter(adapter_instance)
    model = adapter.solver_input
    sample = _build_feasible_sample(name, size, model)
    sampleset = dimod.SampleSet.from_samples_cqm(sample, model)
    return BenchmarkOperation(
        setup=lambda: sampleset,
        run=lambda solver_result: adapter.decode(solver_result),
    )
