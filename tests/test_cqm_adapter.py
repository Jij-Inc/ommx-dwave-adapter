from ommx.v1 import Instance, DecisionVariable, Polynomial, Function
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
    constraints = [(Function(sum(w[i] * x[i] for i in range(N))) <= W).set_id(0)]
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(p[i] * x[i] for i in range(N)),
        constraints=constraints,
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
        DecisionVariable.of_type(
            kind=DecisionVariable.BINARY, id=0, lower=0, upper=1, name="x"
        ),
        DecisionVariable.of_type(
            kind=DecisionVariable.INTEGER,
            id=1,
            lower=-20.0,
            upper=20.0,
            name="y",
            subscripts=[],
        ),
        DecisionVariable.of_type(
            kind=DecisionVariable.CONTINUOUS,
            id=2,
            lower=-30,
            upper=30,
            name="z",
            subscripts=[0],
        ),
        DecisionVariable.of_type(
            kind=DecisionVariable.CONTINUOUS,
            id=3,
            # TODO dwave doesn't accept -inf, +inf. how to handle this? should the adapter convert?
            lower=float("-1e30"),
            upper=float("1e30"),
            name="w",
            subscripts=[1, 2],
        ),
    ]
    objective = Polynomial(terms={(0, 1, 2): 2.0, (1, 2): 3.0, (2,): 4.0, (): 5.0})

    instance = Instance.from_components(
        decision_variables=decision_variables,
        objective=objective,
        constraints=[],
        sense=Instance.MINIMIZE,
    )
    with pytest.raises(OMMXDWaveAdapterError):
        OMMXLeapHybridCQMAdapter(instance)

    # cubic function
    objective = decision_variables[0] * decision_variables[1] * decision_variables[2]

    instance = Instance.from_components(
        decision_variables=decision_variables,
        objective=objective,
        constraints=[],
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
        constraints=[],
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
        constraints=[],
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
        constraints=[],
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
    # we have to explicitly set the ids (& the dimod label)
    # so dimod matches the constraint with the expected model,
    # as the id OMMX seems to set automatically seems to depend
    # on _all_ constraints being made across all tests (and thus
    # is unstable if we ever change things)
    constraints = [(x + z >= A).set_id(0), (z == 2).set_id(1)]
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x + y * z,
        constraints=constraints,
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

    constraints = [(x + z >= A).set_id(0), (z == 2).set_id(1)]
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x + y * z,
        constraints=constraints,
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

    constraints = [(x + y * z >= 10).set_id(0)]
    instance = Instance.from_components(
        decision_variables=[x, y, z],
        objective=x * y + z,
        constraints=constraints,
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
    constraints = [Function(sum(w[i] * x[i] for i in range(N))) <= W]
    instance = Instance.from_components(
        decision_variables=x,
        objective=sum(p[i] * x[i] for i in range(N)),
        constraints=constraints,
        sense=Instance.MAXIMIZE,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    # using ExactCQM solver as a testable stand-in
    dimod_sampleset = dimod.ExactCQMSolver().sample_cqm(cqm)
    dimod_sampleset.resolve()

    sampleset = adapter.decode_to_sampleset(dimod_sampleset)
    assert sampleset.raw.sense == Instance.MAXIMIZE

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
        constraints=[],
        sense=Instance.MINIMIZE,
    )
    adapter = OMMXLeapHybridCQMAdapter(instance)
    cqm = adapter.sampler_input

    # using ExactCQM solver as a testable stand-in
    dimod_sampleset = dimod.ExactCQMSolver().sample_cqm(cqm)
    dimod_sampleset.resolve()

    sampleset = adapter.decode_to_sampleset(dimod_sampleset)
    assert sampleset.raw.sense == Instance.MINIMIZE

    best = sampleset.best_feasible
    assert best.objective == 3
    assert len(best.constraints) == 0
    assert best.state.entries[0] == pytest.approx(1)
    assert best.state.entries[1] == pytest.approx(1)
    assert best.state.entries[2] == pytest.approx(1)
