import copy

import pytest
from ommx import (
    ConstraintKind,
    DecisionVariable,
    IndicatorConstraintID,
    Instance,
    InstanceClassMismatch,
    OneHotConstraint,
    OneHotConstraintID,
    Sense,
    Sos1Constraint,
    Sos1ConstraintID,
)
from ommx.adapter import AdapterNotApplicableError

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


def _instance_with_unsupported_special_constraints() -> Instance:
    indicator = DecisionVariable.binary(0)
    one_hot_variables = [DecisionVariable.binary(i) for i in range(1, 3)]
    value = DecisionVariable.continuous(3, lower=0, upper=2)
    return Instance.from_components(
        decision_variables=[indicator, *one_hot_variables, value],
        objective=value,
        active_constraints={},
        active_indicator_constraints={30: (value <= 1).with_indicator(indicator)},
        active_one_hot_constraints={
            10: OneHotConstraint(variables=one_hot_variables),
        },
        active_sos1_constraints={20: Sos1Constraint(variables=one_hot_variables)},
        sense=Sense.Maximize,
    )


def test_recommended_preparation_policies_are_independent() -> None:
    first = OMMXLeapHybridCQMAdapter.recommended_preparation_policy()
    second = OMMXLeapHybridCQMAdapter.recommended_preparation_policy()

    assert first is not second
    first.special_constraints = None
    assert second.special_constraints is not None


@pytest.mark.parametrize(
    "method_name",
    ["sample_without_preparation", "solve_without_preparation"],
    ids=["sample", "solve"],
)
def test_preparation_rejects_unsupported_special_constraints_without_mutating_input(
    method_name: str,
) -> None:
    instance = _instance_with_unsupported_special_constraints()
    before = instance.to_v2_bytes()
    method = getattr(OMMXLeapHybridCQMAdapter, method_name)

    with pytest.raises(AdapterNotApplicableError) as error:
        method(instance, token="dummy")

    mismatches = error.value.report.clause_reports[0].mismatches
    mismatch_types = {type(mismatch) for mismatch in mismatches}
    assert InstanceClassMismatch.IndicatorConstraintsNotAllowed in mismatch_types
    assert InstanceClassMismatch.Sos1ConstraintsNotAllowed in mismatch_types
    assert instance.to_v2_bytes() == before


def test_recommended_preparation_lowers_only_unsupported_special_constraints() -> None:
    instance = _instance_with_unsupported_special_constraints()
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

    assert set(instance.active_constraints) == {
        IndicatorConstraintID(30),
        OneHotConstraintID(10),
        Sos1ConstraintID(20),
    }
    assert not prepared.active_constraints.of_kind(ConstraintKind.Indicator)
    assert set(prepared.active_constraints.of_kind(ConstraintKind.OneHot)) == {
        OneHotConstraintID(10)
    }
    assert not prepared.active_constraints.of_kind(ConstraintKind.Sos1)
    assert prepared.active_special_constraint_kinds == {ConstraintKind.OneHot}
    assert input_class.contains(prepared)
    assert OMMXLeapHybridCQMAdapter.check_applicability(prepared).is_member

    adapter = OMMXLeapHybridCQMAdapter(prepared)
    assert adapter.instance is prepared
