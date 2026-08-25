"""Tests for the aligned OMMX v2 OneHot preparation baseline."""

import itertools

import pytest
from ommx.v1 import State

from benchmarks.instance import build_one_hot_instance
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


@pytest.mark.parametrize(
    "special_constraints",
    ["indicator", "sos1", "indicator-sos1"],
)
def test_one_hot_preparation_baseline_has_aligned_constraint_count(
    special_constraints,
):
    size = 4
    instance = build_one_hot_instance(
        size,
        formulation="one-hot",
        special_constraints=special_constraints,
    )

    assert len(instance.decision_variables) == size**2
    assert len(instance.constraints) == size * 2
    assert instance.constraint_hints is not None
    assert len(instance.constraint_hints.one_hot_constraints) == size
    assert len(OMMXLeapHybridCQMAdapter(instance).solver_input.variables) == size**2


@pytest.mark.parametrize(
    "special_constraints",
    ["indicator", "sos1", "indicator-sos1"],
)
def test_one_hot_preparation_baseline_has_same_feasible_states(
    special_constraints,
):
    size = 2
    baseline = build_one_hot_instance(size, formulation="one-hot")
    direct = build_one_hot_instance(
        size,
        formulation="one-hot",
        special_constraints=special_constraints,
    )
    model = OMMXLeapHybridCQMAdapter(direct).solver_input

    for values in itertools.product((0.0, 1.0), repeat=size**2):
        entries = dict(enumerate(values))
        expected = baseline.evaluate(State(entries=entries))
        evaluation = direct.evaluate(State(entries=entries))
        assert evaluation.feasible == expected.feasible
        assert evaluation.objective == expected.objective
        assert (
            model.check_feasible(entries)  # pyright: ignore[reportArgumentType]
            == expected.feasible
        )
