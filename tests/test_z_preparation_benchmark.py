"""Tests for the aligned OMMX v2 OneHot preparation baseline."""

import itertools

import pytest
from ommx.v1 import Constraint, State

from benchmarks.instance import build_one_hot_preparation_instance
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


@pytest.mark.parametrize(
    ("special_constraints", "expected_extra_constraints"),
    [
        ("none", 0),
        ("indicator", 1),
        ("sos1", 1),
        ("indicator-sos1", 1),
    ],
)
def test_one_hot_preparation_baseline_has_aligned_constraints(
    special_constraints,
    expected_extra_constraints,
):
    size = 4
    instance = build_one_hot_preparation_instance(
        size,
        formulation="one-hot",
        special_constraints=special_constraints,
    )

    assert len(instance.decision_variables) == size**2
    assert len(instance.constraints) == size * (1 + expected_extra_constraints)
    assert instance.constraint_hints is not None
    assert len(instance.constraint_hints.one_hot_constraints) == size
    model = OMMXLeapHybridCQMAdapter(instance).solver_input
    assert len(model.variables) == size**2
    assert len(model.constraints) == len(instance.constraints)

    extra_constraints = instance.constraints[size:]
    assert all(
        constraint.equality == Constraint.LESS_THAN_OR_EQUAL_TO_ZERO
        for constraint in extra_constraints
    )
    assert all(constraint.name is None for constraint in extra_constraints)
    assert all(constraint.subscripts == [] for constraint in extra_constraints)

    indicator_terms = {
        (0,): 3.0,
        (1,): 1.0,
        (2,): 1.0,
        (3,): 1.0,
        (): -3.0,
    }
    sos1_terms = {
        (0,): 1.0,
        (1,): 1.0,
        (2,): 1.0,
        (3,): 1.0,
        (): -1.0,
    }
    if special_constraints in ("indicator", "indicator-sos1"):
        assert extra_constraints[0].function.terms == indicator_terms
    if special_constraints == "sos1":
        assert extra_constraints[0].function.terms == sos1_terms
    if special_constraints == "indicator-sos1":
        assert extra_constraints[-1].function.terms == {
            (12,): 1.0,
            (13,): 1.0,
            (14,): 1.0,
            (15,): 1.0,
            (): -1.0,
        }


@pytest.mark.parametrize(
    "special_constraints",
    ["indicator", "sos1", "indicator-sos1"],
)
def test_one_hot_preparation_baseline_has_same_feasible_states(
    special_constraints,
):
    size = 2
    baseline = build_one_hot_preparation_instance(size)
    direct = build_one_hot_preparation_instance(
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
