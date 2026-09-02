from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import dimod

if __package__:
    from . import instance as benchmark_instances
else:
    import instance as benchmark_instances
from ommx.v1 import Instance

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
    "one-hot-preparation": benchmark_instances.build_one_hot_preparation_instance,
}
INSTANCE_NAMES = tuple(INSTANCE_BUILDERS)
FORMULATIONS = ("regular", "one-hot")
SPECIAL_CONSTRAINT_CASES = ("none", "indicator", "sos1", "indicator-sos1")
OPERATIONS = ("instance-to-model", "result-to-solution")

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
) -> Instance:
    """Select and build a benchmark Instance."""
    if name == "one-hot-preparation":
        return benchmark_instances.build_one_hot_preparation_instance(
            size,
            seed,
            formulation,
            special_constraints,
        )
    if special_constraints != "none":
        raise ValueError(
            "Special constraint counterparts are available only for one-hot-preparation"
        )
    builder = INSTANCE_BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"Unknown benchmark instance: {name}")
    return builder(size, seed, formulation)


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
    elif name == "one-hot-preparation":
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
) -> BenchmarkOperation:
    """Prepare everything outside the measured operation."""
    if operation == "instance-to-model":
        return BenchmarkOperation(
            setup=lambda: instance,
            run=lambda target: OMMXLeapHybridCQMAdapter(target).solver_input,
        )

    if operation != "result-to-solution":
        raise ValueError(f"Unknown operation: {operation}")

    adapter = OMMXLeapHybridCQMAdapter(instance)
    model = adapter.solver_input
    sample = _build_feasible_sample(name, instance, model)
    sampleset = dimod.SampleSet.from_samples_cqm(sample, model)
    return BenchmarkOperation(
        setup=lambda: sampleset,
        run=lambda solver_result: adapter.decode(solver_result),
    )
