"""Tests for the aligned OMMX v2 OneHot preparation baseline."""

import itertools

import pytest
from ommx.v1 import State

from benchmarks.common import make_benchmark_operation
from benchmarks.instance import build_one_hot_preparation_instance
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


@pytest.mark.parametrize(
    "special_constraints",
    ["indicator", "sos1", "indicator-sos1"],
)
def test_one_hot_preparation_baseline_has_aligned_constraint_count(
    special_constraints,
):
    size = 4
    instance = build_one_hot_preparation_instance(
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


@pytest.mark.parametrize("special_constraints", ["none", "indicator"])
def test_end_to_end_uses_v2_solve(monkeypatch, special_constraints):
    instance = build_one_hot_preparation_instance(
        2,
        special_constraints=special_constraints,
    )
    expected_solution = object()
    calls = []

    def fake_solve(cls, target, *, token, time_limit):
        calls.append((cls, target, token, time_limit))
        return expected_solution

    monkeypatch.setenv("DWAVE_API_TOKEN", "test-token")
    monkeypatch.setattr(
        OMMXLeapHybridCQMAdapter,
        "solve",
        classmethod(fake_solve),
    )

    benchmark = make_benchmark_operation(
        "end-to-end",
        instance,
        "one-hot-preparation",
        2,
        5,
    )
    context = benchmark.setup()
    solution = benchmark.run(context)

    assert context is instance
    assert solution is expected_solution
    assert calls == [(OMMXLeapHybridCQMAdapter, instance, "test-token", 5)]
