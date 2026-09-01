import copy

from ommx.adapter import DiagnosticsSink, SamplerAdapter
from ommx import (
    DegreeBound,
    Equality,
    Function,
    Instance,
    InstanceClass,
    InstanceClassClause,
    Kind,
    PreparationPolicy,
    SampleSet,
    Sense,
    Solution,
    SpecialConstraintKind,
    SpecialConstraintPreparation,
)

import dimod
from dimod import ConstrainedQuadraticModel
from dimod.sym import Sense as DimodSense
from dimod.typing import VartypeLike
from dwave.system import LeapHybridCQMSampler
from typing import ClassVar, Optional

from .exception import OMMXDWaveAdapterError

ABSOLUTE_TOLERANCE = 1e-6
# Maximum supported bounds reported by dimod.vartype_info(dimod.INTEGER/REAL).
_MAX_ABS_INTEGER_BOUND = 2**53 - 1
_MAX_ABS_CONTINUOUS_BOUND = 1e30

_DIMOD_VARIABLE_TYPES: dict[Kind, VartypeLike] = {
    Kind.Binary: dimod.BINARY,
    Kind.Integer: dimod.INTEGER,
    Kind.Continuous: dimod.REAL,
}
_DIMOD_CONSTRAINT_SENSES: dict[Equality, DimodSense] = {
    Equality.EqualToZero: DimodSense.Eq,
    Equality.LessThanOrEqualToZero: DimodSense.Le,
}


class OMMXLeapHybridCQMAdapter(SamplerAdapter):
    INPUT_CLASS: ClassVar[InstanceClass] = InstanceClass(
        [
            InstanceClassClause(
                label="dwave-cqm",
                allowed_variable_kinds=set(_DIMOD_VARIABLE_TYPES),
                objective_degree_bound=DegreeBound.at_most(2),
                regular_constraint_degree_bounds={
                    Equality.EqualToZero: DegreeBound.at_most(2),
                    Equality.LessThanOrEqualToZero: DegreeBound.at_most(2),
                },
                allows_one_hot=True,
                allowed_senses={Sense.Minimize, Sense.Maximize},
            )
        ]
    )

    @classmethod
    def recommended_preparation_policy(cls) -> PreparationPolicy:
        """Recommend lowering unsupported special constraints for D-Wave CQM.

        D-Wave CQM accepts OneHot constraints directly, so this recommendation
        preserves them and lowers only Indicator and SOS1 constraints. The
        returned policy is fresh and caller-editable.
        """
        return PreparationPolicy(
            special_constraints=SpecialConstraintPreparation.lower_special_constraints(
                kinds={
                    SpecialConstraintKind.Indicator,
                    SpecialConstraintKind.Sos1,
                }
            )
        )

    def __init__(self, ommx_instance: Instance):
        """
        :param ommx_instance: The ommx.Instance to sample.
        """
        self.require_applicable(ommx_instance)

        self.instance = ommx_instance
        self.model = ConstrainedQuadraticModel()

        self._set_decision_variables()
        self._set_objective()
        self._set_constraints()

    @classmethod
    def sample(
        cls,
        ommx_instance: Instance,
        *,
        token: Optional[str] = None,
        time_limit: Optional[int] = None,
        label: Optional[str] = None,
        diagnostics: DiagnosticsSink | None = None,
    ) -> SampleSet:
        """Solve the given ommx.Instance using dwave's LeapHybridCQMSampler,
        returning the samples as an ommx.SampleSet.

        ``diagnostics`` are not available through this Adapter.
        The reserved ``diagnostics`` argument is accepted for compatibility with
        the OMMX SamplerAdapter interface.

        **NOTE** The `token` must be specified either through the optional
          parameter or the DWave config file. Refer to DWave documentation for
          more info.

        :param ommx_instance: The ommx.Instance to prepare and sample.
        :param token: Token for instantiating the DWave sampler, obtained from your Leap account.
        :param time_limit: Maximum time the solver will use, in seconds. Must be greater than the minimum time limit specified by DWave (currently 5)
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx import Instance, DecisionVariable
            >>>
            >>> x1 = DecisionVariable.integer(1, lower=0, upper=5)
            >>> ommx_instance = Instance.from_components(
            ...     decision_variables=[x1],
            ...     objective=x1,
            ...     constraints={},
            ...     sense=Instance.MINIMIZE,
            ... )
            >>> token = "YOUR API TOKEN" # Set your API token
            >>> sample_set = OMMXLeapHybridCQMAdapter.sample(ommx_instance, token=token) # doctest: +SKIP
        """
        prepared = copy.copy(ommx_instance)
        prepared.prepare(
            cls.INPUT_CLASS,
            cls.recommended_preparation_policy(),
        )
        return cls.sample_without_preparation(
            prepared,
            token=token,
            time_limit=time_limit,
            label=label,
            diagnostics=diagnostics,
        )

    @classmethod
    def sample_without_preparation(
        cls,
        ommx_instance: Instance,
        *,
        token: Optional[str] = None,
        time_limit: Optional[int] = None,
        label: Optional[str] = None,
        diagnostics: DiagnosticsSink | None = None,
    ) -> SampleSet:
        """Sample an exact D-Wave CQM Adapter input without preparing it.

        Use this method when the input instance has already been prepared,
        possibly with a custom policy, or already belongs to ``INPUT_CLASS``.

        ``diagnostics`` are not available through this Adapter.
        The reserved ``diagnostics`` argument is accepted for compatibility with
        the OMMX SamplerAdapter interface.

        **NOTE** The ``token`` must be specified either through the optional
          parameter or the D-Wave config file. Refer to D-Wave documentation for
          more info.

        :param ommx_instance: The exact D-Wave CQM Adapter input to sample.
        :param token: Token for instantiating the D-Wave sampler.
        :param time_limit: Maximum solver time in seconds.
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.
        """
        # Dwave appears to be able to read configuration from a config file
        # automatically, and this apparently includes the token. Users may want
        # to use the file as a way to pass the token, so we can't necessarily
        # give an error on an empty token

        _ = diagnostics
        adapter = cls(ommx_instance)
        model = adapter.sampler_input
        sampler = LeapHybridCQMSampler(token=token)

        # TODO is this necessary or will it always just go for the minimum if no time limit is set?
        if (
            time_limit is None
            or time_limit < sampler.properties["minimum_time_limit_s"]
        ):
            time_limit = sampler.properties["minimum_time_limit_s"]

        dimod_sampleset = sampler.sample_cqm(model, time_limit=time_limit, label=label)
        dimod_sampleset.resolve()

        return adapter.decode_to_sampleset(dimod_sampleset)

    @classmethod
    def solve(
        cls,
        ommx_instance: Instance,
        *,
        token: Optional[str] = None,
        time_limit: Optional[int] = None,
        label: Optional[str] = None,
        diagnostics: DiagnosticsSink | None = None,
    ) -> Solution:
        """Solve the given ommx.Instance using dwave's LeapHybridCQMSampler,
        returning the best feasible solution as an ommx.Solution.

        ``diagnostics`` are not available through this Adapter.
        The reserved ``diagnostics`` argument is accepted for compatibility with
        the OMMX SamplerAdapter interface.

        **NOTE** The `token` must be specified either through the optional
          parameter or the DWave config file. Refer to DWave documentation for
          more info.

        :param ommx_instance: The ommx.Instance to prepare and solve.
        :param token: Token for instantiating the DWave sampler, obtained from your Leap account.
        :param time_limit: Maximum time the solver will use, in seconds. Must be greater than the minimum time limit specified by DWave (currently 5)
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx import Instance, DecisionVariable
            >>>
            >>> x1 = DecisionVariable.integer(1, lower=0, upper=5)
            >>> ommx_instance = Instance.from_components(
            ...     decision_variables=[x1],
            ...     objective=x1,
            ...     constraints={},
            ...     sense=Instance.MINIMIZE,
            ... )
            >>> token = "YOUR API TOKEN" # Set your API token
            >>> solution = OMMXLeapHybridCQMAdapter.solve(ommx_instance, token=token) # doctest: +SKIP
        """
        prepared = copy.copy(ommx_instance)
        prepared.prepare(
            cls.INPUT_CLASS,
            cls.recommended_preparation_policy(),
        )
        return cls.solve_without_preparation(
            prepared,
            token=token,
            time_limit=time_limit,
            label=label,
            diagnostics=diagnostics,
        )

    @classmethod
    def solve_without_preparation(
        cls,
        ommx_instance: Instance,
        *,
        token: Optional[str] = None,
        time_limit: Optional[int] = None,
        label: Optional[str] = None,
        diagnostics: DiagnosticsSink | None = None,
    ) -> Solution:
        """Solve an exact D-Wave CQM Adapter input without preparing it.

        Use this method when the input instance has already been prepared,
        possibly with a custom policy, or already belongs to ``INPUT_CLASS``.

        ``diagnostics`` are not available through this Adapter.
        The reserved ``diagnostics`` argument is accepted for compatibility with
        the OMMX SamplerAdapter interface.

        **NOTE** The ``token`` must be specified either through the optional
          parameter or the D-Wave config file. Refer to D-Wave documentation for
          more info.

        :param ommx_instance: The exact D-Wave CQM Adapter input to solve.
        :param token: Token for instantiating the D-Wave sampler.
        :param time_limit: Maximum solver time in seconds.
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.
        """
        return cls.sample_without_preparation(
            ommx_instance,
            token=token,
            time_limit=time_limit,
            label=label,
            diagnostics=diagnostics,
        ).best_feasible

    @property
    def sampler_input(self) -> ConstrainedQuadraticModel:
        """The dimod.ConstrainedQuadraticModel representing this OMMX instance"""
        return self.model

    @property
    def solver_input(self) -> ConstrainedQuadraticModel:
        """The dimod.ConstrainedQuadraticModel representing this OMMX instance"""
        return self.model

    def decode_to_sampleset(self, data: dimod.SampleSet) -> SampleSet:
        """Convert a dimod.SampleSet model matching this instance to an ommx.SampleSet.

        This method is intended to be used if the model has been acquired with
        `sampler_input` for further adjustment of the sampler parameters, and
        separately optimizing the model.

        Note that alterations to the model may make the decoding process
        incompatible -- decoding will only work if the model still describes
        effectively the same problem as the OMMX instance used to create the
        adapter.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx import Instance, DecisionVariable
            >>> from dwave.system import LeapHybridCQMSampler
            >>> x1 = DecisionVariable.integer(1, lower=0, upper=5)
            >>> ommx_instance = Instance.from_components(
            ...     decision_variables=[x1],
            ...     objective=x1,
            ...     constraints={},
            ...     sense=Instance.MINIMIZE,
            ... )
            >>>
            >>> adapter = OMMXLeapHybridCQMAdapter(ommx_instance)
            >>> model = adapter.sampler_input # obtain dimod.ConstrainedQuadraticModel
            >>> sampler = LeapHybridCQMSampler() # doctest: +SKIP
            >>> # ... some modification of the sampler parameters
            >>> dimod_sampleset = sampler.sample_cqm(model) # doctest: +SKIP
            >>> sample = adapter.decode_to_sampleset(dimod_sampleset)  # doctest: +SKIP
        """
        # the only type info we have with vars in data.variables is that they're
        # Hashable. We know they are integers but we hash them anyway for type
        # safety. As we stored our variables as integer the hash should still be
        # our IDs
        samples = {
            i: {
                var.__hash__(): float(coeff)
                for var, coeff in zip(data.variables, sample)
            }
            for i, sample in enumerate(data.record.sample)
        }
        return self.instance.evaluate_samples(samples)

    def decode(self, data: dimod.SampleSet) -> Solution:
        """Convert a dimod.SampleSet model matching this instance to an ommx.Solution."""
        sample_set = self.decode_to_sampleset(data)
        return sample_set.best_feasible

    def _set_decision_variables(self):
        for var in self.instance.used_decision_variables:
            kind = Kind.from_pb(var.kind)
            lower_limit = None
            upper_limit = None
            if kind == Kind.Binary:
                # dimod ignores bounds passed to add_variable for binary variables,
                # but keep explicit limits here for consistency with the other kinds.
                lower_limit = 0
                upper_limit = 1
            elif kind == Kind.Integer:
                lower_limit = -_MAX_ABS_INTEGER_BOUND
                upper_limit = _MAX_ABS_INTEGER_BOUND
            elif kind == Kind.Continuous:
                lower_limit = -_MAX_ABS_CONTINUOUS_BOUND
                upper_limit = _MAX_ABS_CONTINUOUS_BOUND
            else:
                raise AssertionError(
                    "Unsupported decision variable kind reached after applicability "
                    f"validation: {kind}. This may indicate an OMMX implementation "
                    "bug; please report it to OMMX."
                )

            if var.bound.lower < lower_limit:
                raise OMMXDWaveAdapterError(
                    f"D-Wave CQM {str(kind).lower()} variable {var.id} has lower "
                    f"bound {var.bound.lower}, below {lower_limit}."
                )
            if var.bound.upper > upper_limit:
                raise OMMXDWaveAdapterError(
                    f"D-Wave CQM {str(kind).lower()} variable {var.id} has upper "
                    f"bound {var.bound.upper}, above {upper_limit}."
                )

            self.model.add_variable(
                _DIMOD_VARIABLE_TYPES[kind],
                var.id,
                lower_bound=var.bound.lower,
                upper_bound=var.bound.upper,
            )

    def _set_objective(self):
        objective = self.instance.objective

        expr = self._make_expr(objective)

        if self.instance.sense == Instance.MINIMIZE:
            pass
        elif self.instance.sense == Instance.MAXIMIZE:
            # multiply all coefficients by -1:
            # this takes all except the last element from the tuple and concatenates it
            # with the last element multiplied with -1 to get a new tuple
            expr = [term[:-1] + (-1 * term[-1],) for term in expr]
        else:
            raise AssertionError(
                "Unsupported objective sense reached after applicability validation: "
                f"{self.instance.sense}. This may indicate an OMMX implementation "
                "bug; please report it to OMMX."
            )

        # Set objective function
        self.model.set_objective(expr)

    def _set_constraints(self):
        # Handle OneHot constraints (first-class constraint type)
        one_hot_variable_ids = set()
        selected_one_hot_constraints = []
        regularized_one_hot_constraints = []
        # Prefer constraints with more variables. The stable sort keeps the order
        # from one_hot_constraints when two constraints have the same length.
        # This selection policy follows the existing ommx-da4-adapter behavior.
        sorted_one_hot_constraints = sorted(
            self.instance.one_hot_constraints.items(),
            key=lambda item: len(item[1].variables),
            reverse=True,
        )

        for constraint_id, constraint in sorted_one_hot_constraints:
            if not one_hot_variable_ids.isdisjoint(constraint.variables):
                # dimod discrete constraints must be disjoint. Preserve the
                # overlapping OneHot as an equivalent regular equality constraint.
                regularized_one_hot_constraints.append((constraint_id, constraint))
                continue

            selected_one_hot_constraints.append((constraint_id, constraint))
            one_hot_variable_ids.update(constraint.variables)

        for constraint_id, constraint in selected_one_hot_constraints:
            self.model.add_discrete_from_iterable(
                constraint.variables,
                label=f"onehot_{constraint_id}",
                check_overlaps=False,
            )

        for constraint_id, constraint in regularized_one_hot_constraints:
            self.model.add_constraint_from_iterable(
                ((variable_id, 1.0) for variable_id in constraint.variables),
                DimodSense.Eq,
                rhs=1.0,
                label=f"onehot_{constraint_id}",
            )

        for constraint_id, constraint in self.instance.constraints.items():
            # Only constant case
            if constraint.function.degree() == 0:
                if constraint.evaluate({}, atol=ABSOLUTE_TOLERANCE).feasible:
                    continue
                raise OMMXDWaveAdapterError(
                    f"Infeasible constant constraint was found: id {constraint_id}"
                )

            # Create dwave expression for the constraint
            expr = self._make_expr(constraint.function)

            if constraint.equality not in _DIMOD_CONSTRAINT_SENSES:
                raise AssertionError(
                    "Unsupported constraint equality reached after applicability "
                    f"validation: {constraint.equality} for constraint "
                    f"{constraint_id}. This may indicate an OMMX implementation "
                    "bug; please report it to OMMX."
                )

            # rhs is assumed 0 by dwave
            self.model.add_constraint_from_iterable(
                expr,
                _DIMOD_CONSTRAINT_SENSES[constraint.equality],
                label=constraint_id,
            )

    def _make_expr(self, function: Function):
        """Create a dwave expression from an OMMX Function."""
        expr = []
        for ids, coefficient in function.terms.items():
            expr.append((*ids, coefficient))

        return expr
