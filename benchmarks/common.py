from collections.abc import Callable
from importlib.metadata import version
from typing import Any

from dwave.system import LeapHybridCQMSampler
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
    version("dwave-system"),
    version("ommx_dwave_adapter"),
)


def build_instance(name: str, size: int, seed: int, formulation: str) -> Instance:
    """Select and build a benchmark Instance."""
    return INSTANCE_BUILDERS[name](size, seed, formulation)


def prepare_target(
    operation: str, instance: Instance, solver_time_limit: float
) -> Callable[[], Any]:
    """Prepare everything outside the measured operation."""
    if operation == "instance-to-model":
        return lambda: OMMXLeapHybridCQMAdapter(instance).solver_input

    adapter = OMMXLeapHybridCQMAdapter(instance)
    model = adapter.solver_input
    sampler = LeapHybridCQMSampler()
    time_limit = max(solver_time_limit, sampler.min_time_limit(model))
    result = sampler.sample_cqm(model, time_limit=time_limit)
    result.resolve()
    return lambda: adapter.decode(result)
