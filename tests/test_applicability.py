import pytest

from ommx import (
    DecisionVariable,
    DegreeBound,
    Equality,
    Instance,
    InstanceClassMismatch,
    Kind,
    OneHotConstraint,
    Sense,
    Sos1Constraint,
)
from ommx.adapter import AdapterNotApplicableError

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter


def test_declares_quadratic_cqm_input_class() -> None:
    input_class = OMMXLeapHybridCQMAdapter.INPUT_CLASS
    [clause] = input_class.clauses

    assert clause.label == "dwave-cqm"
    assert clause.allowed_variable_kinds == {
        Kind.Binary,
        Kind.Integer,
        Kind.Continuous,
    }
    assert clause.objective_degree_bound == DegreeBound.at_most(2)
    assert clause.regular_constraint_degree_bounds == {
        Equality.EqualToZero: DegreeBound.at_most(2),
        Equality.LessThanOrEqualToZero: DegreeBound.at_most(2),
    }
    assert clause.indicator_constraint_degree_bounds == {}
    assert clause.allows_one_hot
    assert not clause.allows_sos1
    assert clause.allowed_senses == {Sense.Minimize, Sense.Maximize}


@pytest.mark.parametrize("sense", [Sense.Minimize, Sense.Maximize])
def test_input_class_accepts_complete_quadratic_cqm_boundary(sense):
    b0 = DecisionVariable.binary(0)
    b1 = DecisionVariable.binary(1)
    x = DecisionVariable.integer(2, lower=-3, upper=3)
    y = DecisionVariable.continuous(3, lower=-3, upper=3)
    instance = Instance.from_components(
        decision_variables=[b0, b1, x, y],
        objective=b0 * x + y,
        constraints={0: x * x <= 9, 1: b1 * x == 0},
        one_hot_constraints={10: OneHotConstraint(variables=[b0, b1])},
        sense=sense,
    )

    report = OMMXLeapHybridCQMAdapter.check_applicability(instance)

    assert report.is_member
    assert report.matching_clauses == [(0, "dwave-cqm")]


def test_error_on_unsupported_function():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=x[0] * x[1] * x[2],
        constraints={},
        sense=Sense.Minimize,
    )

    with pytest.raises(AdapterNotApplicableError) as error:
        OMMXLeapHybridCQMAdapter(instance)

    mismatches = error.value.report.clause_reports[0].mismatches
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert isinstance(mismatch, InstanceClassMismatch.ObjectiveDegreeExceedsBound)
    assert mismatch.actual_degree == 3
    assert mismatch.bound == DegreeBound.at_most(2)


def test_error_on_unsupported_constraint():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        constraints={7: x[0] * x[1] * x[2] == 0},
        sense=Sense.Minimize,
    )

    with pytest.raises(AdapterNotApplicableError) as error:
        OMMXLeapHybridCQMAdapter(instance)

    mismatches = error.value.report.clause_reports[0].mismatches
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert isinstance(
        mismatch, InstanceClassMismatch.RegularConstraintDegreeExceedsBound
    )
    assert mismatch.actual_degrees == {7: 3}
    assert mismatch.bound == DegreeBound.at_most(2)


@pytest.mark.parametrize(
    ("variable", "kind"),
    [
        (DecisionVariable.semi_integer(0, lower=1, upper=3), Kind.SemiInteger),
        (
            DecisionVariable.semi_continuous(0, lower=1, upper=3),
            Kind.SemiContinuous,
        ),
    ],
)
def test_rejects_unsupported_variable_kinds(variable, kind):
    instance = Instance.from_components(
        decision_variables=[variable],
        objective=variable,
        constraints={},
        sense=Sense.Minimize,
    )

    with pytest.raises(AdapterNotApplicableError) as error:
        OMMXLeapHybridCQMAdapter(instance)

    mismatches = error.value.report.clause_reports[0].mismatches
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert isinstance(mismatch, InstanceClassMismatch.VariableKindNotAllowed)
    assert mismatch.kind == kind
    assert mismatch.variable_ids == {0}


def test_reports_unsupported_special_constraint_ids():
    x = DecisionVariable.binary(0)
    y = DecisionVariable.continuous(1)
    instance = Instance.from_components(
        decision_variables=[x, y],
        objective=x + y,
        constraints={},
        indicator_constraints={10: (y <= 1).with_indicator(x)},
        sos1_constraints={30: Sos1Constraint(variables=[y])},
        sense=Sense.Minimize,
    )
    with pytest.raises(AdapterNotApplicableError) as error:
        OMMXLeapHybridCQMAdapter(instance)

    mismatches = error.value.report.clause_reports[0].mismatches
    by_type = {type(mismatch): mismatch for mismatch in mismatches}
    indicator = by_type[InstanceClassMismatch.IndicatorConstraintsNotAllowed]
    assert isinstance(indicator, InstanceClassMismatch.IndicatorConstraintsNotAllowed)
    assert indicator.constraint_ids == {10}
    sos1 = by_type[InstanceClassMismatch.Sos1ConstraintsNotAllowed]
    assert isinstance(sos1, InstanceClassMismatch.Sos1ConstraintsNotAllowed)
    assert sos1.constraint_ids == {30}
