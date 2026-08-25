import copy
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import dimod
from instance import (
    build_assignment_instance,
    build_blending_instance,
    build_clique_instance,
    build_facility_location_instance,
    build_knapsack_instance,
    build_one_hot_instance,
    build_portfolio_cardinality_instance,
    build_portfolio_instance,
    build_production_instance,
    build_tsp_instance,
    build_unit_commitment_instance,
)
from ommx import Instance

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter

INSTANCE_BUILDERS = {
    "knapsack": build_knapsack_instance,
    "one-hot": build_one_hot_instance,
    "production": build_production_instance,
    "blending": build_blending_instance,
    "assignment": build_assignment_instance,
    "facility-location": build_facility_location_instance,
    "portfolio": build_portfolio_instance,
    "portfolio-cardinality": build_portfolio_cardinality_instance,
    "unit-commitment": build_unit_commitment_instance,
    "clique": build_clique_instance,
    "tsp": build_tsp_instance,
}
INSTANCE_NAMES = tuple(INSTANCE_BUILDERS)
FORMULATIONS = ("regular", "one-hot")
SPECIAL_CONSTRAINT_CASES = ("none", "indicator", "sos1", "indicator-sos1")
PREPARATIONS = ("none", "recommended")

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
    if name == "one-hot":
        return build_one_hot_instance(
            size,
            seed,
            formulation,
            special_constraints,
            preparation,
        )
    if special_constraints != "none":
        raise ValueError("Special constraints are available only for one-hot")
    if preparation != "none":
        raise ValueError(
            "Preparation is available only for one-hot special constraints"
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
    elif name == "one-hot":
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

    adapter_instance = (
        _prepare_instance(instance) if preparation == "recommended" else instance
    )
    if operation == "instance-to-model":
        return BenchmarkOperation(
            setup=lambda: adapter_instance,
            run=lambda target: OMMXLeapHybridCQMAdapter(target).solver_input,
        )

    adapter = OMMXLeapHybridCQMAdapter(adapter_instance)
    model = adapter.solver_input
    sample = _build_feasible_sample(name, size, model)
    sampleset = dimod.SampleSet.from_samples_cqm(sample, model)
    return BenchmarkOperation(
        setup=lambda: sampleset,
        run=lambda solver_result: adapter.decode(solver_result),
    )
