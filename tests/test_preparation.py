import copy

import pytest

from ommx import (
    DecisionVariable,
    Instance,
    OneHotConstraint,
    Sense,
    Sos1Constraint,
    SpecialConstraintKind,
)
from ommx.adapter import AdapterNotApplicableError

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


def test_recommended_preparation_policies_are_independent() -> None:
    first = OMMXLeapHybridCQMAdapter.recommended_preparation_policy()
    second = OMMXLeapHybridCQMAdapter.recommended_preparation_policy()

    assert first is not second
    first.special_constraints = None
    assert second.special_constraints is not None


def test_recommended_preparation_lowers_only_unsupported_special_constraints() -> None:
    indicator = DecisionVariable.binary(0)
    one_hot_variables = [DecisionVariable.binary(i) for i in range(1, 3)]
    value = DecisionVariable.continuous(3, lower=0, upper=2)
    instance = Instance.from_components(
        decision_variables=[indicator, *one_hot_variables, value],
        objective=value,
        constraints={},
        indicator_constraints={30: (value <= 1).with_indicator(indicator)},
        one_hot_constraints={
            10: OneHotConstraint(variables=one_hot_variables),
        },
        sos1_constraints={20: Sos1Constraint(variables=one_hot_variables)},
        sense=Sense.Maximize,
    )
    before = instance.to_v2_bytes()
    input_class = OMMXLeapHybridCQMAdapter.INPUT_CLASS

    assert not OMMXLeapHybridCQMAdapter.check_applicability(instance).is_member
    with pytest.raises(AdapterNotApplicableError):
        OMMXLeapHybridCQMAdapter(instance)
    assert instance.to_v2_bytes() == before

    prepared = copy.copy(instance)
    prepared.prepare(
        input_class,
        OMMXLeapHybridCQMAdapter.recommended_preparation_policy(),
    )

    assert set(instance.indicator_constraints) == {30}
    assert set(instance.one_hot_constraints) == {10}
    assert set(instance.sos1_constraints) == {20}
    assert prepared.indicator_constraints == {}
    assert set(prepared.one_hot_constraints) == {10}
    assert prepared.sos1_constraints == {}
    assert prepared.active_special_constraint_kinds == {
        SpecialConstraintKind.OneHot,
    }
    assert input_class.contains(prepared)
    assert OMMXLeapHybridCQMAdapter.check_applicability(prepared).is_member

    adapter = OMMXLeapHybridCQMAdapter(prepared)
    assert adapter.instance is prepared
