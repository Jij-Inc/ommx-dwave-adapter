import copy
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
)

_ALL_ZERO_SAMPLE_INSTANCES = {
    "knapsack",
    "production",
    "facility-location",
    "portfolio",
    "portfolio-cardinality",
}

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
    builder = INSTANCE_BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"Unknown benchmark instance: {name}")
    return builder(size, seed, formulation)


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
    name: str, instance: Instance, model: dimod.ConstrainedQuadraticModel
) -> dict[int, float]:
    """Build a deterministic feasible sample from Instance variable metadata."""
    variables = {variable.id: variable for variable in instance.decision_variables}
    if set(variables) != set(model.variables):
        raise AssertionError(f"Benchmark Instance variables do not match {name} model")

    sample = {variable_id: 0.0 for variable_id in variables}

    if name in _ALL_ZERO_SAMPLE_INSTANCES:
        pass
    elif name == "blending":
        sample.update({variable_id: 1.0 for variable_id in variables})
    elif name == PREPARATION_INSTANCE_NAME:
        sample.update(
            {
                variable_id: 1.0
                for variable_id, variable in variables.items()
                if variable.name == "x" and variable.subscripts[1] == 0
            }
        )
    elif name in ("assignment", "tsp"):
        sample.update(
            {
                variable_id: 1.0
                for variable_id, variable in variables.items()
                if variable.name == "x"
                and variable.subscripts[0] == variable.subscripts[1]
            }
        )
    elif name == "unit-commitment":
        sample.update(
            {
                variable_id: 1.0 if variable.name == "u" else 5.0
                for variable_id, variable in variables.items()
            }
        )
    elif name == "clique":
        ordered_vertices = sorted(
            variables.items(), key=lambda item: item[1].subscripts[0]
        )
        clique_size = (len(ordered_vertices) + 1) // 2
        sample.update(
            {variable_id: 1.0 for variable_id, _ in ordered_vertices[-clique_size:]}
        )
    else:
        raise ValueError(f"No deterministic benchmark sample for instance: {name}")

    if not model.check_feasible(sample):  # pyright: ignore[reportArgumentType]
        raise AssertionError(f"Benchmark sample is not feasible for {name} model")

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

    if operation != "result-to-solution":
        raise ValueError(f"Unknown operation: {operation}")

    adapter = OMMXLeapHybridCQMAdapter(adapter_instance)
    model = adapter.solver_input
    sample = _build_feasible_sample(name, adapter_instance, model)
    sampleset = dimod.SampleSet.from_samples_cqm(sample, model)
    return BenchmarkOperation(
        setup=lambda: sampleset,
        run=lambda solver_result: adapter.decode(solver_result),
    )
