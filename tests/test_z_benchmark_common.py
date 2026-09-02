"""Tests for the token-free benchmark operation helpers."""

import pytest

from benchmarks.common import (
    _build_feasible_sample,
    build_instance,
    make_benchmark_operation,
)
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


@pytest.mark.parametrize(
    ("name", "formulation"),
    [
        ("knapsack", "regular"),
        ("production", "regular"),
        ("blending", "regular"),
        ("assignment", "one-hot"),
        ("facility-location", "regular"),
        ("portfolio", "regular"),
        ("portfolio-cardinality", "regular"),
        ("unit-commitment", "regular"),
        ("clique", "regular"),
        ("tsp", "one-hot"),
        ("one-hot-preparation", "one-hot"),
    ],
)
def test_deterministic_sample_matches_benchmark_model(name, formulation):
    size = 4
    instance = build_instance(name, size, 0, formulation)
    model = OMMXLeapHybridCQMAdapter(instance).solver_input

    sample = _build_feasible_sample(name, size, model)

    assert set(sample) == set(model.variables)
    assert model.check_feasible(sample)  # pyright: ignore[reportArgumentType]

    benchmark = make_benchmark_operation(
        "result-to-solution",
        instance,
        name,
        size,
    )
    assert benchmark.run(benchmark.setup()) is not None


@pytest.mark.parametrize(
    "special_constraints",
    ["none", "indicator", "sos1", "indicator-sos1"],
)
def test_preparation_counterpart_has_a_decodable_sample(special_constraints):
    instance = build_instance(
        "one-hot-preparation",
        4,
        0,
        "one-hot",
        special_constraints,
    )
    benchmark = make_benchmark_operation(
        "result-to-solution",
        instance,
        "one-hot-preparation",
        4,
    )

    assert benchmark.run(benchmark.setup()) is not None


def test_unknown_instance_name_is_rejected():
    with pytest.raises(ValueError, match="Unknown benchmark instance"):
        build_instance("unknown", 4, 0, "regular")

    instance = build_instance("knapsack", 4, 0, "regular")
    model = OMMXLeapHybridCQMAdapter(instance).solver_input
    with pytest.raises(ValueError, match="No deterministic benchmark sample"):
        _build_feasible_sample("unknown", 4, model)
