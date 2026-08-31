"""Verify that OMMX v2 OneHot hints do not change the D-Wave CQM."""

import pytest

from benchmarks.instance import build_assignment_instance, build_tsp_instance
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


@pytest.mark.parametrize(
    "build_instance",
    [build_assignment_instance, build_tsp_instance],
    ids=["assignment", "tsp"],
)
def test_one_hot_formulation_converts_to_the_regular_model(build_instance):
    size = 4
    regular = build_instance(size, formulation="regular")
    one_hot = build_instance(size, formulation="one-hot")

    regular_hints = regular.constraint_hints
    assert regular_hints is None or len(regular_hints.one_hot_constraints) == 0
    one_hot_hints = one_hot.constraint_hints
    assert one_hot_hints is not None
    assert len(one_hot_hints.one_hot_constraints) == 2 * size

    regular_model = OMMXLeapHybridCQMAdapter(regular).solver_input
    one_hot_model = OMMXLeapHybridCQMAdapter(one_hot).solver_input
    assert regular_model.is_equal(one_hot_model)
