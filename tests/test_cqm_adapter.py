from ommx import Instance, DecisionVariable, Polynomial, Function, OneHotConstraint
from dimod.sym import Sense
import dimod
import pytest

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter, OMMXDWaveAdapterError


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
    constraints = Function(sum(w[i] * x[i] for i in range(N))) <= W
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(p[i] * x[i] for i in range(N)),
        constraints={0: constraints},
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

    assert model.constraints[0].sense == Sense.Le
    assert model.constraints[0].lhs.offset == -W
    assert model.constraints[0].lhs.linear == {x[i].id: w[i] for i in range(N)}
    assert model.constraints[0].rhs == 0


def test_error_on_unsupported_function():
    decision_variables = [
        DecisionVariable.binary(
            id=0,
            name="x",
        ),
        DecisionVariable.integer(id=1, name="y", lower=-20, upper=20),
        DecisionVariable.continuous(
            id=2, name="z", lower=-30, upper=30, subscripts=[0]
        ),
        DecisionVariable.continuous(
            id=3, name="w", lower=float("-1e30"), upper=float("1e30"), subscripts=[1, 2]
        ),  # TODO dwave doesn't accept -inf, +inf. how to handle this? should the adapter convert?
    ]
    objective = Polynomial(terms={(0, 1, 2): 2.0, (1, 2): 3.0, (2,): 4.0, (): 5.0})

    instance = Instance.from_components(
        decision_variables=decision_variables,
        objective=objective,
        constraints={},
        sense=Instance.MINIMIZE,
    )
    with pytest.raises(OMMXDWaveAdapterError):
        OMMXLeapHybridCQMAdapter(instance)

    # cubic function
    objective = decision_variables[0] * decision_variables[1] * decision_variables[2]

    instance = Instance.from_components(
        decision_variables=decision_variables,
        objective=objective,
        constraints={},
        sense=Instance.MINIMIZE,
    )
    with pytest.raises(OMMXDWaveAdapterError):
        OMMXLeapHybridCQMAdapter(instance)


def test_encode_single_var_types():
    N = 3
    xs = [DecisionVariable.binary(id=i) for i in range(N)]
    ws = [i + 1 for i in range(N)]
    instance = Instance.from_components(
        decision_variables=xs,
        objective=sum(ws[i] * xs[i] for i in range(N)),
        constraints={},
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
        constraints={},
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
        constraints={},
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
        constraints={0: constraint_1, 1: constraint_2},
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
    expected.add_constraint(-dimod_x - dimod_z + A <= 0, label=0)
    expected.add_constraint(dimod_z - 2 == 0, label=1)

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
        objective=x + y * z,
        constraints={0: constraint_1, 1: constraint_2},
        sense=Instance.MAXIMIZE,
    )

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x = dimod.Real(0, lower_bound=-10, upper_bound=10)
    dimod_y = dimod.Binary(1)
    dimod_z = dimod.Integer(2, lower_bound=1, upper_bound=10)
    expected.set_objective(-dimod_x - dimod_y * dimod_z)
    expected.add_constraint(-dimod_x - dimod_z + A <= 0, label=0)
    expected.add_constraint(dimod_z - 2 == 0, label=1)

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    assert cqm.is_equal(expected)


def test_encode_quadratic():
    x = DecisionVariable.integer(id=0, name="x", lower=10, upper=20)
    y = DecisionVariable.integer(id=1, name="y", lower=10, upper=20)
    z = DecisionVariable.integer(id=2, name="z", lower=10, upper=20)

    constraints = x + y * z >= 10
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x * y + z,
        constraints={0: constraints},
        sense=Instance.MINIMIZE,
    )

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x = dimod.Integer(0, lower_bound=10, upper_bound=20)
    dimod_y = dimod.Integer(1, lower_bound=10, upper_bound=20)
    dimod_z = dimod.Integer(2, lower_bound=10, upper_bound=20)
    expected.set_objective(dimod_x * dimod_y + dimod_z)
    expected.add_constraint(-dimod_x - dimod_y * dimod_z + 10 <= 0, label=0)

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
    constraints = Function(sum(w[i] * x[i] for i in range(N))) <= W
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(p[i] * x[i] for i in range(N)),
        constraints={0: constraints},
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


def test_decode_no_constraints():
    x = [
        DecisionVariable.integer(id=i, name="x", subscripts=[i], lower=1, upper=10)
        for i in range(3)
    ]
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(x[i] for i in range(3)),
        constraints={},
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
        constraints={0: x[0] + x[1] + x[2] <= 1},
        sense=Instance.MINIMIZE,
    )
    assert instance.used_decision_variables == x
    partial = instance.partial_evaluate({0: 1})
    # x[0] is no longer present in the problem
    assert partial.used_decision_variables == x[1:]

    adapter = OMMXLeapHybridCQMAdapter(partial)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x1 = dimod.Binary(1)
    dimod_x2 = dimod.Binary(2)
    expected.set_objective(dimod_x1 + dimod_x2 + 1)
    expected.add_constraint(dimod_x1 + dimod_x2 <= 0, label=0)

    assert cqm.is_equal(expected)

    # Test partial evaluation with x[1] = 1
    partial = instance.partial_evaluate({1: 1})
    adapter = OMMXLeapHybridCQMAdapter(partial)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x0 = dimod.Binary(0)
    dimod_x2 = dimod.Binary(2)
    expected.set_objective(dimod_x0 + dimod_x2 + 1)
    expected.add_constraint(dimod_x0 + dimod_x2 <= 0, label=0)

    assert cqm.is_equal(expected)

    # Test partial evaluation with x[2] = 1
    partial = instance.partial_evaluate({2: 1})
    adapter = OMMXLeapHybridCQMAdapter(partial)
    cqm = adapter.sampler_input

    expected = dimod.ConstrainedQuadraticModel()
    dimod_x0 = dimod.Binary(0)
    dimod_x1 = dimod.Binary(1)
    expected.set_objective(dimod_x0 + dimod_x1 + 1)
    expected.add_constraint(dimod_x0 + dimod_x1 <= 0, label=0)

    assert cqm.is_equal(expected)


def test_relax_constraint():
    x = [DecisionVariable.binary(i, name="x", subscripts=[i]) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=x[0] + x[1],
        constraints={0: x[0] + 2 * x[1] <= 1, 1: x[1] + x[2] <= 1},
        sense=Instance.MINIMIZE,
    )

    assert instance.used_decision_variables == x
    instance.relax_constraint(1, "relax")
    # id for x[2] is listed as irrelevant
    assert instance.irrelevant_decision_variable_ids() == {x[2].id}

    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    # Create expected model after relaxing constraint 1
    expected = dimod.ConstrainedQuadraticModel()
    dimod_x0 = dimod.Binary(0)
    dimod_x1 = dimod.Binary(1)
    expected.set_objective(dimod_x0 + dimod_x1)
    expected.add_constraint(dimod_x0 + 2 * dimod_x1 - 1 <= 0, label=0)

    assert cqm.is_equal(expected)


def test_encode_one_hot_constraint():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        constraints={},
        one_hot_constraints={0: OneHotConstraint(variables=[0, 1, 2])},
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert list(model.variables) == [0, 1, 2]
    assert model.objective.linear == {}
    assert model.objective.quadratic == {}
    assert model.objective.offset == 0

    label = "onehot_0"
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
        constraints={},
        one_hot_constraints={
            0: OneHotConstraint(variables=[0, 1, 2]),
            1: OneHotConstraint(variables=[3, 4, 5]),
        },
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    expected_variables = {
        "onehot_0": {0: 1, 1: 1, 2: 1},
        "onehot_1": {3: 1, 4: 1, 5: 1},
    }
    for label, variables in expected_variables.items():
        assert label in model.constraints
        assert label in model.discrete
        assert model.constraints[label].sense == Sense.Eq
        assert model.constraints[label].lhs.linear == variables
        assert model.constraints[label].rhs == 1


def test_regular_and_one_hot_constraint_labels_do_not_conflict():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        constraints={0: x[0] + x[1] <= 1},
        one_hot_constraints={0: OneHotConstraint(variables=[0, 1, 2])},
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert 0 in model.constraints
    assert "onehot_0" in model.constraints
    assert 0 not in model.discrete
    assert "onehot_0" in model.discrete


def test_overlapping_one_hot_constraint_is_converted():
    x = [DecisionVariable.binary(i) for i in range(4)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        constraints={},
        one_hot_constraints={
            0: OneHotConstraint(variables=[0, 1]),
            1: OneHotConstraint(variables=[1, 2, 3]),
        },
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert set(instance.one_hot_constraints) == {1}
    assert set(instance.removed_one_hot_constraints) == {0}
    assert set(instance.constraints) == {0}

    assert set(model.discrete) == {"onehot_1"}
    assert model.constraints["onehot_1"].lhs.linear == {1: 1, 2: 1, 3: 1}
    assert model.constraints["onehot_1"].rhs == 1

    assert 0 in model.constraints
    assert 0 not in model.discrete
    assert model.constraints[0].sense == Sense.Eq
    assert model.constraints[0].lhs.linear == {0: 1, 1: 1}
    assert model.constraints[0].lhs.offset == -1
    assert model.constraints[0].rhs == 0


def test_equal_length_overlapping_one_hot_constraints_keep_first():
    x = [DecisionVariable.binary(i) for i in range(3)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        constraints={},
        one_hot_constraints={
            1: OneHotConstraint(variables=[1, 2]),
            0: OneHotConstraint(variables=[0, 1]),
        },
        sense=Instance.MINIMIZE,
    )
    constraint_ids = list(instance.one_hot_constraints)

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert set(instance.one_hot_constraints) == {constraint_ids[0]}
    assert set(instance.removed_one_hot_constraints) == {constraint_ids[1]}
    assert set(model.discrete) == {f"onehot_{constraint_ids[0]}"}


def test_overlapping_one_hot_constraints_use_greedy_selection():
    x = [DecisionVariable.binary(i) for i in range(7)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=0,
        constraints={},
        one_hot_constraints={
            0: OneHotConstraint(variables=[0, 1, 2, 3]),
            1: OneHotConstraint(variables=[0, 4, 5]),
            2: OneHotConstraint(variables=[4, 6]),
        },
        sense=Instance.MINIMIZE,
    )

    model = OMMXLeapHybridCQMAdapter(instance).sampler_input

    assert set(instance.one_hot_constraints) == {0, 2}
    assert set(instance.removed_one_hot_constraints) == {1}
    assert set(model.discrete) == {"onehot_0", "onehot_2"}
