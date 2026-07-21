from collections.abc import Callable
from importlib.metadata import version
from typing import Any

import dimod
from ommx import Instance

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter

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

PACKAGE_VERSIONS = (
    version("ommx"),
    version("dimod"),
    version("dwave-system"),
    version("ommx_dwave_adapter"),
)


def build_instance(name: str, size: int, seed: int, formulation: str) -> Instance:
    """Select and build a benchmark Instance."""
    return INSTANCE_BUILDERS[name](size, seed, formulation)


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


def prepare_target(
    operation: str, instance: Instance, name: str, size: int
) -> Callable[[], Any]:
    """Prepare everything outside the measured operation."""
    if operation == "instance-to-model":
        return lambda: OMMXLeapHybridCQMAdapter(instance).solver_input

    adapter = OMMXLeapHybridCQMAdapter(instance)
    model = adapter.solver_input
    sample = _build_feasible_sample(name, size, model)
    sampleset = dimod.SampleSet.from_samples_cqm(sample, model)
    return lambda: adapter.decode(sampleset)
