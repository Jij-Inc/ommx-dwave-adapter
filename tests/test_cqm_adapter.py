import copy
from unittest.mock import MagicMock, Mock

import dimod
import pytest
from dimod.sym import Sense
from ommx import (
    Bound,
    ConstraintKind,
    DecisionVariable,
    Function,
    Instance,
    Kind,
    OneHotConstraint,
    OneHotConstraintID,
)
from ommx import (
    Sense as OMMXSense,
)

from ommx_dwave_adapter import OMMXDWaveAdapterError, OMMXLeapHybridCQMAdapter
from ommx_dwave_adapter.adapter import (
    _MAX_ABS_CONTINUOUS_BOUND,
    _MAX_ABS_INTEGER_BOUND,
    ABSOLUTE_TOLERANCE,
)


@pytest.mark.parametrize(
    "variable",
    [
        DecisionVariable.binary(0),
        DecisionVariable.integer(
            0,
            lower=-_MAX_ABS_INTEGER_BOUND,
            upper=_MAX_ABS_INTEGER_BOUND,
        ),
        DecisionVariable.continuous(
            0,
            lower=-_MAX_ABS_CONTINUOUS_BOUND,
            upper=_MAX_ABS_CONTINUOUS_BOUND,
        ),
    ],
)
def test_accepts_dwave_variable_boundaries(variable):
    instance = Instance.from_components(
        decision_variables=[variable],
        objective=variable,
        active_constraints={},
        sense=OMMXSense.Minimize,
    )

    report = OMMXLeapHybridCQMAdapter.check_applicability(instance)

    assert report.is_member
    OMMXLeapHybridCQMAdapter(instance)


@pytest.mark.parametrize("fixed_value", [0, 1])
def test_fixed_binary_bound_preserves_feasible_set(fixed_value):
    x = DecisionVariable(7, Kind.Binary, Bound(fixed_value, fixed_value))
    instance = Instance.from_components(
        decision_variables=[x],
        objective=x,
        active_constraints={},
        sense=OMMXSense.Maximize if fixed_value == 0 else OMMXSense.Minimize,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    samples = dimod.ExactCQMSolver().sample_cqm(adapter.sampler_input)
    feasible = samples.filter(lambda row: row.is_feasible)
    assert [row[x.id] for row in feasible.samples()] == [fixed_value]
    assert adapter.decode(feasible).state.entries == {x.id: fixed_value}


@pytest.mark.parametrize(
    ("variable", "expected_message"),
    [
        (
            DecisionVariable.integer(
                0,
                lower=-(_MAX_ABS_INTEGER_BOUND + 1),
                upper=0,
            ),
            "D-Wave CQM integer variable 0 has lower bound",
        ),
        (
            DecisionVariable.integer(
                0,
                lower=0,
                upper=_MAX_ABS_INTEGER_BOUND + 1,
            ),
            "D-Wave CQM integer variable 0 has upper bound",
        ),
        (
            DecisionVariable.continuous(
                0,
                lower=-2 * _MAX_ABS_CONTINUOUS_BOUND,
                upper=0,
            ),
            "D-Wave CQM continuous variable 0 has lower bound",
        ),
        (
            DecisionVariable.continuous(
                0,
                lower=0,
                upper=2 * _MAX_ABS_CONTINUOUS_BOUND,
            ),
            "D-Wave CQM continuous variable 0 has upper bound",
        ),
    ],
)
def test_rejects_out_of_range_dwave_variable_bound_during_conversion(
    variable, expected_message
):
    instance = Instance.from_components(
        decision_variables=[variable],
        objective=variable,
        active_constraints={},
        sense=OMMXSense.Minimize,
    )

    report = OMMXLeapHybridCQMAdapter.check_applicability(instance)

    assert report.is_member
    with pytest.raises(OMMXDWaveAdapterError, match=expected_message):
        OMMXLeapHybridCQMAdapter(instance)


@pytest.mark.parametrize(
    ("variable", "kind"),
    [
        (DecisionVariable.integer(0), "integer"),
        (DecisionVariable.continuous(0), "continuous"),
    ],
)
def test_rejects_default_unbounded_dwave_variable(variable, kind):
    instance = Instance.from_components(
        decision_variables=[variable],
        objective=variable,
        active_constraints={},
        sense=OMMXSense.Minimize,
    )

    report = OMMXLeapHybridCQMAdapter.check_applicability(instance)

    assert report.is_member
    with pytest.raises(
        OMMXDWaveAdapterError,
        match=f"D-Wave CQM {kind} variable 0 has lower bound",
    ):
        OMMXLeapHybridCQMAdapter(instance)


def test_skips_feasible_constant_constraints():
    x = DecisionVariable.binary(0)
    instance = Instance.from_components(
        decision_variables=[x],
        objective=x,
        active_constraints={
            0: Function(ABSOLUTE_TOLERANCE / 2) == 0,
            1: Function(-ABSOLUTE_TOLERANCE / 2) == 0,
            2: Function(ABSOLUTE_TOLERANCE / 2) <= 0,
            3: Function(-1) <= 0,
        },
        sense=OMMXSense.Minimize,
    )

    adapter = OMMXLeapHybridCQMAdapter(instance)

    assert len(adapter.sampler_input.constraints) == 0


@pytest.mark.parametrize(
    "constraint",
    [
        Function(2 * ABSOLUTE_TOLERANCE) == 0,
        Function(2 * ABSOLUTE_TOLERANCE) <= 0,
    ],
    ids=["equality", "less-than-or-equal"],
)
def test_rejects_infeasible_constant_constraint(constraint):
    x = DecisionVariable.binary(0)
    instance = Instance.from_components(
        decision_variables=[x],
        objective=x,
        active_constraints={7: constraint},
        sense=OMMXSense.Minimize,
    )

    with pytest.raises(OMMXDWaveAdapterError, match=r"id ConstraintID\(7\)"):
        OMMXLeapHybridCQMAdapter(instance)


def test_instance_to_cqm_model():
    # simple knapsack problem
    p = [10, 13, 18, 31, 7, 15]
    w = [11, 25, 20, 35, 10, 33]
    W = 47
    N = len(p)

    x = [
        DecisionVariable.binary(
            id=i,
            name="x",
            subscripts=[i],
        )
        for i in range(N)
    ]
    constraint = Function(sum(w[i] * x[i] for i in range(N))) <= W
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(p[i] * x[i] for i in range(N)),
        active_constraints={0: constraint},
        sense=Instance.MAXIMIZE,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    model = adapter.solver_input
    assert model.vartype(x[0].id) == dimod.BINARY
    assert list(model.variables) == [var.id for var in x]

    assert model.objective.quadratic == {}
    # MAXIMIZE check: dwave only minimizes, so all coefficients must have had their sign changed
    assert model.objective.linear == {x[i].id: -p[i] for i in range(N)}
    assert model.objective.offset == 0.0

    assert model.constraints["ConstraintID(0)"].sense == Sense.Le
    assert model.constraints["ConstraintID(0)"].lhs.offset == -W
    assert model.constraints["ConstraintID(0)"].lhs.linear == {
        x[i].id: w[i] for i in range(N)
    }
    assert model.constraints["ConstraintID(0)"].rhs == 0


def test_encode_single_var_types():
    N = 3
    xs = [DecisionVariable.binary(id=i) for i in range(N)]
    ws = [i + 1 for i in range(N)]
    instance = Instance.from_components(
        decision_variables=xs,
        objective=sum(ws[i] * xs[i] for i in range(N)),
        active_constraints={},
        sense=Instance.MINIMIZE,
    )

    dimod_xs = list(dimod.Binaries([i for i in range(N)]))
    expected = dimod.ConstrainedQuadraticModel()
    expected.set_objective(sum(ws[i] * dimod_xs[i] for i in range(N)))

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input
    assert cqm.is_equal(expected)

    xs = [DecisionVariable.integer(id=i, lower=-10, upper=10) for i in range(N)]
    instance = Instance.from_components(
        decision_variables=xs,
        objective=sum(ws[i] * xs[i] for i in range(N)),
        active_constraints={},
        sense=Instance.MINIMIZE,
    )

    dimod_xs = [
        dimod.Integer(label=i, lower_bound=-10, upper_bound=10) for i in range(N)
    ]
    expected = dimod.ConstrainedQuadraticModel()
    expected.set_objective(sum(ws[i] * dimod_xs[i] for i in range(N)))

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input
    assert cqm.is_equal(expected)

    xs = [DecisionVariable.continuous(id=i, lower=-10, upper=10) for i in range(N)]
    instance = Instance.from_components(
        decision_variables=xs,
        objective=sum(ws[i] * xs[i] for i in range(N)),
        active_constraints={},
        sense=Instance.MINIMIZE,
    )

    dimod_xs = [dimod.Real(label=i, lower_bound=-10, upper_bound=10) for i in range(N)]
    expected = dimod.ConstrainedQuadraticModel()
    expected.set_objective(sum(ws[i] * dimod_xs[i] for i in range(N)))

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input
    assert cqm.is_equal(expected)


def test_encode_multi_variable_types():
    x = DecisionVariable.continuous(id=0, name="x", lower=-10, upper=10)
    y = DecisionVariable.binary(id=1, name="y")
    z = DecisionVariable.integer(id=2, name="z", lower=1, upper=10)
    A = 2
    constraint_1 = x + z >= A
    constraint_2 = z == 2
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x + y * z,
        active_constraints={0: constraint_1, 1: constraint_2},
        sense=Instance.MINIMIZE,
    )

    expected = dimod.ConstrainedQuadraticModel()
    # we currently use IDs as labels
    dimod_x = dimod.Real(0, lower_bound=-10, upper_bound=10)
    dimod_y = dimod.Binary(1)
    dimod_z = dimod.Integer(2, lower_bound=1, upper_bound=10)
    expected.set_objective(dimod_x + dimod_y * dimod_z)
    # OMMX will have automatically converted the expression `x + z >= A` into a
    # `<= 0` form. So it's equivalent to `- x - z + A <= 0  `
    expected.add_constraint(-dimod_x - dimod_z + A <= 0, label="ConstraintID(0)")
    expected.add_constraint(dimod_z - 2 == 0, label="ConstraintID(1)")

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    assert cqm.is_equal(expected)
    assert cqm.vartype(0) == dimod.Vartype.REAL
    assert cqm.vartype(1) == dimod.Vartype.BINARY
    assert cqm.vartype(2) == dimod.Vartype.INTEGER


def test_encode_maximize():
    # same model as the multi vartypes tests, but with MAXIMIZE sense.
    # so we expect the objective in the dimod model to be multiplied by -1

    x = DecisionVariable.continuous(id=0, name="x", lower=-10, upper=10)
    y = DecisionVariable.binary(id=1, name="y")
    z = DecisionVariable.integer(id=2, name="z", lower=1, upper=10)
    A = 2

    constraint_1 = x + z >= A
    constraint_2 = z == 2
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x + y * z + 3,
        active_constraints={0: constraint_1, 1: constraint_2},
        sense=Instance.MAXIMIZE,
    )

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x = dimod.Real(0, lower_bound=-10, upper_bound=10)
    dimod_y = dimod.Binary(1)
    dimod_z = dimod.Integer(2, lower_bound=1, upper_bound=10)
    expected.set_objective(-dimod_x - dimod_y * dimod_z - 3)
    expected.add_constraint(-dimod_x - dimod_z + A <= 0, label="ConstraintID(0)")
    expected.add_constraint(dimod_z - 2 == 0, label="ConstraintID(1)")

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    assert cqm.is_equal(expected)


def test_encode_quadratic():
    x = DecisionVariable.integer(id=0, name="x", lower=10, upper=20)
    y = DecisionVariable.integer(id=1, name="y", lower=10, upper=20)
    z = DecisionVariable.integer(id=2, name="z", lower=10, upper=20)

    constraint = x + y * z >= 10
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x * y + z,
        active_constraints={0: constraint},
        sense=Instance.MINIMIZE,
    )

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x = dimod.Integer(0, lower_bound=10, upper_bound=20)
    dimod_y = dimod.Integer(1, lower_bound=10, upper_bound=20)
    dimod_z = dimod.Integer(2, lower_bound=10, upper_bound=20)
    expected.set_objective(dimod_x * dimod_y + dimod_z)
    expected.add_constraint(
        -dimod_x - dimod_y * dimod_z + 10 <= 0, label="ConstraintID(0)"
    )

    assert cqm.is_equal(expected)


def test_decode():
    p = [10, 13, 18, 31, 7, 15]
    w = [11, 25, 20, 35, 10, 33]
    W = 47
    N = len(p)

    x = [
        DecisionVariable.binary(
            id=i,
            name="x",
            subscripts=[i],
        )
        for i in range(N)
    ]
    constraint = Function(sum(w[i] * x[i] for i in range(N))) <= W
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(p[i] * x[i] for i in range(N)),
        active_constraints={0: constraint},
        sense=Instance.MAXIMIZE,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    # using ExactCQM solver as a testable stand-in
    dimod_sampleset = dimod.ExactCQMSolver().sample_cqm(cqm)
    dimod_sampleset.resolve()

    sampleset = adapter.decode_to_sampleset(dimod_sampleset)
    assert sampleset.sense == Instance.MAXIMIZE

    best = sampleset.best_feasible
    assert best.objective == 41
    assert best.state.entries[0] == pytest.approx(1)
    assert best.state.entries[1] == pytest.approx(0)
    assert best.state.entries[2] == pytest.approx(0)
    assert best.state.entries[3] == pytest.approx(1)
    assert best.state.entries[4] == pytest.approx(0)
    assert best.state.entries[5] == pytest.approx(0)


@pytest.mark.parametrize(("time_limit", "expected"), [(None, None), (3, 5), (10, 10)])
def test_sample_forwards_time_limit(monkeypatch, time_limit, expected):
    instance = Instance.minimize()
    x = instance.new_binary("x")
    instance.objective = x
    sampler = MagicMock()
    sampler.__enter__.return_value = sampler
    sampler.properties = {"minimum_time_limit_s": 5}
    sampler.sample_cqm.return_value = dimod.SampleSet.from_samples(
        {x.id: 0}, vartype=dimod.BINARY, energy=0
    )
    monkeypatch.setattr(
        "ommx_dwave_adapter.adapter.LeapHybridCQMSampler", Mock(return_value=sampler)
    )

    OMMXLeapHybridCQMAdapter.sample(instance, time_limit=time_limit)

    assert sampler.sample_cqm.call_args.kwargs["time_limit"] == expected
    sampler.__exit__.assert_called_once_with(None, None, None)


def test_sampler_closes_when_resolving_fails(monkeypatch):
    sampler = MagicMock()
    sampler.__enter__.return_value = sampler
    failure = RuntimeError("solver failed")
    sampler.sample_cqm.return_value.resolve.side_effect = failure
    monkeypatch.setattr(
        "ommx_dwave_adapter.adapter.LeapHybridCQMSampler", Mock(return_value=sampler)
    )

    with pytest.raises(RuntimeError, match="solver failed"):
        OMMXLeapHybridCQMAdapter.solve(Instance.minimize())
    assert sampler.__exit__.call_args.args[:2] == (RuntimeError, failure)


@pytest.mark.parametrize("sense", [OMMXSense.Minimize, OMMXSense.Maximize])
def test_solve_evaluates_each_observed_row_once(monkeypatch, sense):
    x, y = (DecisionVariable.binary(i) for i in range(2))
    instance = Instance.from_components(
        decision_variables=[x, y],
        objective=x + y,
        active_constraints={0: x + y >= 1},
        sense=sense,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    samples = dimod.SampleSet.from_samples_cqm(
        [{0: 1, 1: 1}, {0: 0, 1: 0}, {0: 1, 1: 0}, {0: 0, 1: 1}],
        adapter.sampler_input,
        num_occurrences=[0, 3, 2, 5],
    )
    expected = adapter.decode_to_sampleset(samples).best_feasible
    monkeypatch.setattr(
        OMMXLeapHybridCQMAdapter, "_sample_cqm", Mock(return_value=samples)
    )
    evaluate_samples = Instance.evaluate_samples
    evaluated_counts = []

    def record_count(instance, samples):
        evaluated_counts.append(samples.num_samples())
        return evaluate_samples(instance, samples)

    monkeypatch.setattr(Instance, "evaluate_samples", record_count)
    best = OMMXLeapHybridCQMAdapter.solve(instance)
    assert evaluated_counts == [3]
    assert best.feasible
    assert best.state.entries == expected.state.entries


def test_decode_preserves_occurrences():
    instance = Instance.maximize()
    x = instance.new_binary("x")
    instance.objective = x
    adapter = OMMXLeapHybridCQMAdapter(instance)
    samples = dimod.SampleSet.from_samples_cqm(
        [{x.id: 0}, {x.id: 1}], adapter.sampler_input, num_occurrences=[1, 3]
    )

    decoded = adapter.decode_to_sampleset(samples)
    assert decoded.num_samples() == 4
    assert decoded.objectives == {0: 0, 1: 1, 2: 1, 3: 1}


@pytest.mark.parametrize("count", [-1, 0.9, 1.1, float("nan"), float("inf")])
def test_decode_rejects_invalid_occurrence_count(count):
    instance = Instance.minimize()
    x = instance.new_binary("x")
    instance.objective = x
    adapter = OMMXLeapHybridCQMAdapter(instance)
    samples = dimod.SampleSet.from_samples_cqm(
        [{x.id: 0}, {x.id: 1}], adapter.sampler_input, num_occurrences=[1, count]
    )
    with pytest.raises(OMMXDWaveAdapterError, match="num_occurrences.*row 1"):
        adapter.decode_to_sampleset(samples)
    with pytest.raises(OMMXDWaveAdapterError, match="num_occurrences.*row 1"):
        adapter.decode(samples)


def test_decode_accepts_integer_valued_counts_and_zero():
    instance = Instance.minimize()
    x = instance.new_binary("x")
    instance.objective = x
    adapter = OMMXLeapHybridCQMAdapter(instance)
    samples = dimod.SampleSet.from_samples_cqm(
        [{x.id: 0}, {x.id: 1}], adapter.sampler_input, num_occurrences=[0.0, 2.0]
    )
    assert adapter.decode_to_sampleset(samples).objectives == {0: 1, 1: 1}


def test_decode_with_caller_supplied_copy(monkeypatch):
    instance = Instance.maximize()
    x = instance.new_binary("x")
    instance.objective = x
    supplied = copy.copy(instance)
    adapter = OMMXLeapHybridCQMAdapter(supplied)
    samples = dimod.ExactCQMSolver().sample_cqm(adapter.sampler_input)

    instance.objective = 1 - x
    instance.add_constraint(x == 0)

    evaluate_samples = Instance.evaluate_samples

    def evaluate_supplied(model, samples):
        assert model is supplied
        return evaluate_samples(model, samples)

    monkeypatch.setattr(Instance, "evaluate_samples", evaluate_supplied)
    best = adapter.decode(samples)
    assert best.state.entries == {x.id: 1}
    assert best.objective == 1
    assert best.feasible


def test_decode_no_constraints():
    x = [
        DecisionVariable.integer(id=i, name="x", subscripts=[i], lower=1, upper=10)
        for i in range(3)
    ]
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(x[i] for i in range(3)),
        active_constraints={},
        sense=Instance.MINIMIZE,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    # using ExactCQM solver as a testable stand-in
    dimod_sampleset = dimod.ExactCQMSolver().sample_cqm(cqm)
    dimod_sampleset.resolve()

    sampleset = adapter.decode_to_sampleset(dimod_sampleset)
    assert sampleset.sense == Instance.MINIMIZE

    best = sampleset.best_feasible
    assert best.objective == 3
    assert len(best.constraints) == 0
    assert best.state.entries[0] == pytest.approx(1)
    assert best.state.entries[1] == pytest.approx(1)
    assert best.state.entries[2] == pytest.approx(1)


def test_partial_evaluate():
    x = [DecisionVariable.binary(i, name="x", subscripts=[i]) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=x[0] + x[1] + x[2],
        active_constraints={0: x[0] + x[1] + x[2] <= 1},
        sense=Instance.MINIMIZE,
    )
    assert instance.active_decision_variables == x
    partial = instance.partial_evaluate({0: 1})
    # x[0] is no longer present in the problem
    assert partial.active_decision_variables == x[1:]

    adapter = OMMXLeapHybridCQMAdapter(partial)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x1 = dimod.Binary(1)
    dimod_x2 = dimod.Binary(2)
    expected.set_objective(dimod_x1 + dimod_x2 + 1)
    expected.add_constraint(dimod_x1 + dimod_x2 <= 0, label="ConstraintID(0)")

    assert cqm.is_equal(expected)

    # Test partial evaluation with x[1] = 1
    partial = instance.partial_evaluate({1: 1})
    adapter = OMMXLeapHybridCQMAdapter(partial)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x0 = dimod.Binary(0)
    dimod_x2 = dimod.Binary(2)
    expected.set_objective(dimod_x0 + dimod_x2 + 1)
    expected.add_constraint(dimod_x0 + dimod_x2 <= 0, label="ConstraintID(0)")

    assert cqm.is_equal(expected)

    # Test partial evaluation with x[2] = 1
    partial = instance.partial_evaluate({2: 1})
    adapter = OMMXLeapHybridCQMAdapter(partial)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x0 = dimod.Binary(0)
    dimod_x1 = dimod.Binary(1)
    expected.set_objective(dimod_x0 + dimod_x1 + 1)
    expected.add_constraint(dimod_x0 + dimod_x1 <= 0, label="ConstraintID(0)")

    assert cqm.is_equal(expected)


def test_deactivate_constraint():
    x = [DecisionVariable.binary(i, name="x", subscripts=[i]) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=x[0] + x[1],
        active_constraints={0: x[0] + 2 * x[1] <= 1, 1: x[1] + x[2] <= 1},
        sense=Instance.MINIMIZE,
    )

    assert instance.active_decision_variables == x
    instance.deactivate_constraint(1, "relax")
    # id for x[2] is listed as irrelevant
    assert instance.irrelevant_decision_variable_ids() == {x[2].id}

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    # Create expected model after relaxing constraint 1
    expected = dimod.ConstrainedQuadraticModel()
    dimod_x0 = dimod.Binary(0)
    dimod_x1 = dimod.Binary(1)
    expected.set_objective(dimod_x0 + dimod_x1)
    expected.add_constraint(dimod_x0 + 2 * dimod_x1 - 1 <= 0, label="ConstraintID(0)")

    assert cqm.is_equal(expected)


def test_encode_one_hot_constraint():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        active_constraints={},
        active_one_hot_constraints={0: OneHotConstraint(variables=[x[0], x[1], x[2]])},
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert list(model.variables) == [0, 1, 2]
    assert model.objective.linear == {}
    assert model.objective.quadratic == {}
    assert model.objective.offset == 0

    label = "OneHotConstraintID(0)"
    assert label in model.constraints
    assert label in model.discrete
    assert model.constraints[label].sense == Sense.Eq
    assert model.constraints[label].lhs.linear == {0: 1, 1: 1, 2: 1}
    assert model.constraints[label].rhs == 1


def test_encode_multiple_disjoint_one_hot_constraints():
    x = [DecisionVariable.binary(i) for i in range(6)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        active_constraints={},
        active_one_hot_constraints={
            0: OneHotConstraint(variables=[x[0], x[1], x[2]]),
            1: OneHotConstraint(variables=[x[3], x[4], x[5]]),
        },
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    expected_variables = {
        "OneHotConstraintID(0)": {0: 1, 1: 1, 2: 1},
        "OneHotConstraintID(1)": {3: 1, 4: 1, 5: 1},
    }
    for label, variables in expected_variables.items():
        assert label in model.constraints
        assert label in model.discrete
        assert model.constraints[label].sense == Sense.Eq
        assert model.constraints[label].lhs.linear == variables
        assert model.constraints[label].rhs == 1


def test_regular_and_one_hot_constraint_labels_survive_cqm_serialization():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        active_constraints={1: x[0] + x[1] <= 1},
        active_one_hot_constraints={0: OneHotConstraint(variables=[x[0], x[1], x[2]])},
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert "ConstraintID(1)" in model.constraints
    assert "OneHotConstraintID(0)" in model.constraints
    assert "ConstraintID(1)" not in model.discrete
    assert "OneHotConstraintID(0)" in model.discrete
    with model.to_file() as serialized:
        restored = dimod.ConstrainedQuadraticModel.from_file(serialized.read())
    assert restored.is_equal(model)


def test_overlapping_one_hot_constraint_is_encoded_without_mutating_input():
    x = [DecisionVariable.binary(i) for i in range(4)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        active_constraints={},
        active_one_hot_constraints={
            0: OneHotConstraint(variables=[x[0], x[1]]),
            1: OneHotConstraint(variables=[x[1], x[2], x[3]]),
        },
        sense=Instance.MINIMIZE,
    )
    before = instance.to_v2_bytes()

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert instance.to_v2_bytes() == before
    assert set(instance.active_constraints.of_kind(ConstraintKind.OneHot)) == {
        OneHotConstraintID(0),
        OneHotConstraintID(1),
    }
    assert not instance.inactive_constraints.of_kind(ConstraintKind.OneHot)
    assert not instance.active_constraints.of_kind(ConstraintKind.Regular)

    assert set(model.discrete) == {"OneHotConstraintID(1)"}
    assert model.constraints["OneHotConstraintID(1)"].lhs.linear == {1: 1, 2: 1, 3: 1}
    assert model.constraints["OneHotConstraintID(1)"].rhs == 1

    assert "OneHotConstraintID(0)" in model.constraints
    assert "OneHotConstraintID(0)" not in model.discrete
    assert model.constraints["OneHotConstraintID(0)"].sense == Sense.Eq
    assert model.constraints["OneHotConstraintID(0)"].lhs.linear == {0: 1, 1: 1}
    assert model.constraints["OneHotConstraintID(0)"].lhs.offset == 0
    assert model.constraints["OneHotConstraintID(0)"].rhs == 1


def test_equal_length_overlapping_one_hot_constraints_keep_first():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        active_constraints={},
        active_one_hot_constraints={
            1: OneHotConstraint(variables=[x[1], x[2]]),
            0: OneHotConstraint(variables=[x[0], x[1]]),
        },
        sense=Instance.MINIMIZE,
    )
    constraint_ids = list(instance.active_constraints.of_kind(ConstraintKind.OneHot))
    before = instance.to_v2_bytes()

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert instance.to_v2_bytes() == before
    assert set(instance.active_constraints.of_kind(ConstraintKind.OneHot)) == set(
        constraint_ids
    )
    assert not instance.inactive_constraints.of_kind(ConstraintKind.OneHot)
    assert not instance.active_constraints.of_kind(ConstraintKind.Regular)
    assert set(model.discrete) == {str(constraint_ids[0])}
    regularized_label = str(constraint_ids[1])
    regularized = instance.active_constraints.of_kind(ConstraintKind.OneHot)[
        constraint_ids[1]
    ]
    assert model.constraints[regularized_label].sense == Sense.Eq
    assert model.constraints[regularized_label].lhs.linear == {
        variable_id: 1 for variable_id in regularized.variables
    }
    assert model.constraints[regularized_label].rhs == 1


def test_overlapping_one_hot_constraints_use_greedy_selection():
    x = [DecisionVariable.binary(i) for i in range(7)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        active_constraints={},
        active_one_hot_constraints={
            0: OneHotConstraint(variables=[x[0], x[1], x[2], x[3]]),
            1: OneHotConstraint(variables=[x[0], x[4], x[5]]),
            2: OneHotConstraint(variables=[x[4], x[6]]),
        },
        sense=Instance.MINIMIZE,
    )
    before = instance.to_v2_bytes()

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert instance.to_v2_bytes() == before
    assert set(instance.active_constraints.of_kind(ConstraintKind.OneHot)) == {
        OneHotConstraintID(0),
        OneHotConstraintID(1),
        OneHotConstraintID(2),
    }
    assert not instance.inactive_constraints.of_kind(ConstraintKind.OneHot)
    assert not instance.active_constraints.of_kind(ConstraintKind.Regular)
    assert set(model.discrete) == {"OneHotConstraintID(0)", "OneHotConstraintID(2)"}
    expected_constraints = {
        "OneHotConstraintID(0)": {0: 1, 1: 1, 2: 1, 3: 1},
        "OneHotConstraintID(1)": {0: 1, 4: 1, 5: 1},
        "OneHotConstraintID(2)": {4: 1, 6: 1},
    }
    for label, variables in expected_constraints.items():
        assert model.constraints[label].sense == Sense.Eq
        assert model.constraints[label].lhs.linear == variables
        assert model.constraints[label].rhs == 1
