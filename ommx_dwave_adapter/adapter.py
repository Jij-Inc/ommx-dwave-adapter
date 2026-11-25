import copy
from itertools import chain
from typing import ClassVar, final

import dimod
import numpy as np
from dimod import ConstrainedQuadraticModel
from dimod.sym import Sense as DimodSense
from dwave.system import LeapHybridCQMSampler
from ommx import (
    ConstraintKind,
    DecisionVariable,
    Equality,
    Function,
    Instance,
    InstanceClass,
    InstanceClassClause,
    Kind,
    PolynomialRequirement,
    PreparationPolicy,
    Samples,
    SampleSet,
    Sense,
    Solution,
    SpecialConstraintPreparation,
)
from ommx.adapter import DiagnosticsSink, SamplerAdapter

from .exception import OMMXDWaveAdapterError

ABSOLUTE_TOLERANCE = 1e-6
# Maximum supported bounds reported by dimod.vartype_info(dimod.INTEGER/REAL).
_MAX_ABS_INTEGER_BOUND = 2**53 - 1
_MAX_ABS_CONTINUOUS_BOUND = 1e30

_DIMOD_CONSTRAINT_SENSES: dict[Equality, DimodSense] = {
    Equality.EqualToZero: DimodSense.Eq,
    Equality.LessThanOrEqualToZero: DimodSense.Le,
}


@final
class OMMXLeapHybridCQMAdapter(SamplerAdapter):
    """Convert an OMMX instance to a D-Wave constrained quadratic model.

    Continuous variables are supported in linear terms only. Conversion rejects
    quadratic terms containing them in the objective or any active constraint,
    including constraints produced by preparation.
    """

    INPUT_CLASS: ClassVar[InstanceClass] = InstanceClass(
        [
            InstanceClassClause(
                label="dwave-cqm",
                allowed_variable_kinds={
                    Kind.Binary,
                    Kind.Integer,
                    Kind.Continuous,
                },
                objective_polynomial_requirement=PolynomialRequirement.at_most(2),
                regular_constraint_polynomial_requirements={
                    Equality.EqualToZero: PolynomialRequirement.at_most(2),
                    Equality.LessThanOrEqualToZero: PolynomialRequirement.at_most(2),
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
                    ConstraintKind.Indicator,
                    ConstraintKind.Sos1,
                }
            )
        )

    def __init__(self, ommx_instance: Instance):
        """Build the CQM and retain the supplied instance by reference for decoding.

        Keep the instance unchanged from construction until you finish using this
        adapter, including backend configuration, sampling and decoding. Pass
        ``copy.copy(ommx_instance)`` if you need to edit the original meanwhile.
        """
        self.instance = ommx_instance
        self.require_applicable(self.instance)
        self.model = ConstrainedQuadraticModel()

        has_continuous = self._set_decision_variables()
        self._set_objective()
        self._set_constraints()
        if has_continuous:
            self._validate_continuous_terms()

    @classmethod
    def sample(
        cls,
        ommx_instance: Instance,
        *,
        token: str | None = None,
        time_limit: int | None = None,
        label: str | None = None,
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
        :param time_limit: Solver time limit in seconds. If omitted, Ocean chooses the minimum for this model.
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx import Instance
            >>>
            >>> ommx_instance = Instance.minimize()
            >>> x1 = ommx_instance.new_integer("x1", lower=0, upper=5)
            >>> ommx_instance.objective = x1
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
        token: str | None = None,
        time_limit: int | None = None,
        label: str | None = None,
        diagnostics: DiagnosticsSink | None = None,
    ) -> SampleSet:
        """Sample an exact D-Wave CQM Adapter input without preparing it.

        Use this method when the input instance has already been prepared,
        possibly with a custom policy, or already belongs to ``INPUT_CLASS``.
        Keep the supplied instance unchanged for the duration of this call.

        ``diagnostics`` are not available through this Adapter.
        The reserved ``diagnostics`` argument is accepted for compatibility with
        the OMMX SamplerAdapter interface.

        **NOTE** The ``token`` must be specified either through the optional
          parameter or the D-Wave config file. Refer to D-Wave documentation for
          more info.

        :param ommx_instance: The exact D-Wave CQM Adapter input to sample.
        :param token: Token for instantiating the D-Wave sampler.
        :param time_limit: Solver time limit in seconds. If omitted, Ocean chooses the minimum for this model.
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.
        """
        adapter = cls(ommx_instance)
        samples = adapter._sample_cqm(token=token, time_limit=time_limit, label=label)
        return adapter.decode_to_sampleset(samples)

    def _sample_cqm(
        self, *, token: str | None, time_limit: int | None, label: str | None
    ) -> dimod.SampleSet:
        # An omitted token lets Ocean read the credentials from the D-Wave config file.
        with LeapHybridCQMSampler(token=token) as sampler:
            if time_limit is not None:
                time_limit = max(time_limit, sampler.properties["minimum_time_limit_s"])
            samples = sampler.sample_cqm(
                self.sampler_input, time_limit=time_limit, label=label
            )
            samples.resolve()
        return samples

    @classmethod
    def solve(
        cls,
        ommx_instance: Instance,
        *,
        token: str | None = None,
        time_limit: int | None = None,
        label: str | None = None,
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
        :param time_limit: Solver time limit in seconds. If omitted, Ocean chooses the minimum for this model.
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx import Instance
            >>>
            >>> ommx_instance = Instance.minimize()
            >>> x1 = ommx_instance.new_integer("x1", lower=0, upper=5)
            >>> ommx_instance.objective = x1
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
        token: str | None = None,
        time_limit: int | None = None,
        label: str | None = None,
        diagnostics: DiagnosticsSink | None = None,
    ) -> Solution:
        """Solve an exact D-Wave CQM Adapter input without preparing it.

        Use this method when the input instance has already been prepared,
        possibly with a custom policy, or already belongs to ``INPUT_CLASS``.
        Keep the supplied instance unchanged for the duration of this call.

        ``diagnostics`` are not available through this Adapter.
        The reserved ``diagnostics`` argument is accepted for compatibility with
        the OMMX SamplerAdapter interface.

        **NOTE** The ``token`` must be specified either through the optional
          parameter or the D-Wave config file. Refer to D-Wave documentation for
          more info.

        :param ommx_instance: The exact D-Wave CQM Adapter input to solve.
        :param token: Token for instantiating the D-Wave sampler.
        :param time_limit: Solver time limit in seconds. If omitted, Ocean chooses the minimum for this model.
        :param label: Optional label to tag the problem with.
        :param diagnostics: Reserved for OMMX SamplerAdapter compatibility;
          currently unused.
        """
        adapter = cls(ommx_instance)
        samples = adapter._sample_cqm(token=token, time_limit=time_limit, label=label)
        return adapter.decode(samples)

    @property
    def sampler_input(self) -> ConstrainedQuadraticModel:
        """The dimod CQM built from this instance.

        Variable labels are integer OMMX IDs. OMMX constraint labels are
        ``str(constraint_id)``, such as ``"ConstraintID(7)"`` or ``"OneHotConstraintID(2)"``.
        An equality fixing a binary variable is labeled ``fixed_binary_<variable ID>``.
        """
        return self.model

    @property
    def solver_input(self) -> ConstrainedQuadraticModel:
        """The same dimod CQM as :attr:`sampler_input`."""
        return self.model

    def decode_to_sampleset(self, data: dimod.SampleSet) -> SampleSet:
        """Convert a dimod.SampleSet model matching this instance to an ommx.SampleSet.

        This method is intended to be used if the model has been acquired with
        `sampler_input` for further adjustment of the sampler parameters, and
        separately optimizing the model.

        Each occurrence in the dimod result receives its own OMMX sample ID.
        The adapter evaluates the samples against the instance supplied to its constructor.

        Note that alterations to the model may make the decoding process
        incompatible -- decoding will only work if the model still describes
        effectively the same problem as the OMMX instance used to create the
        adapter.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx import Instance
            >>> from dwave.system import LeapHybridCQMSampler
            >>> ommx_instance = Instance.minimize()
            >>> x1 = ommx_instance.new_integer("x1", lower=0, upper=5)
            >>> ommx_instance.objective = x1
            >>>
            >>> adapter = OMMXLeapHybridCQMAdapter(ommx_instance)
            >>> model = adapter.sampler_input # obtain dimod.ConstrainedQuadraticModel
            >>> # ... some modification of the sampler parameters
            >>> with LeapHybridCQMSampler() as sampler:  # doctest: +SKIP
            ...     dimod_sampleset = sampler.sample_cqm(model)
            ...     dimod_sampleset.resolve()
            >>> sample = adapter.decode_to_sampleset(dimod_sampleset)  # doctest: +SKIP
        """
        return self._evaluate_samples(data, expand_occurrences=True)

    def decode(self, data: dimod.SampleSet) -> Solution:
        """Return the best feasible solution, evaluating each observed row once."""
        return self._evaluate_samples(data, expand_occurrences=False).best_feasible

    def _evaluate_samples(
        self, data: dimod.SampleSet, *, expand_occurrences: bool
    ) -> SampleSet:
        samples = Samples({})
        for row, (values, count) in enumerate(
            zip(data.record.sample, data.record.num_occurrences)
        ):
            if isinstance(count, (float, np.floating)) and count.is_integer():
                count = int(count)
            if not isinstance(count, (int, np.integer)) or count < 0:
                raise OMMXDWaveAdapterError(
                    f"Expected a nonnegative integer num_occurrences in row {row}, got {count!r}."
                )
            if count == 0:
                continue
            # dimod types labels as Hashable. This adapter uses integer OMMX IDs
            # and takes their hashes here. Large integer IDs can hash to a
            # different value (see issue #9).
            state = {
                var.__hash__(): float(value)
                for var, value in zip(data.variables, values)
            }
            first_id = samples.num_samples()
            size = int(count) if expand_occurrences else 1
            samples.append(range(first_id, first_id + size), state)
        return self.instance.evaluate_samples(samples)

    def _set_decision_variables(self) -> bool:
        """Add active variables and report whether the CQM contains a continuous variable."""
        has_continuous = False
        for var in self.instance.active_decision_variables:
            if var.kind == DecisionVariable.BINARY:
                kind = dimod.BINARY
                kind_name = "binary"
                # dimod ignores bounds passed to add_variable for binary variables,
                # but keep explicit limits here for consistency with the other kinds.
                lower_limit = 0
                upper_limit = 1
            elif var.kind == DecisionVariable.INTEGER:
                kind = dimod.INTEGER
                kind_name = "integer"
                lower_limit = -_MAX_ABS_INTEGER_BOUND
                upper_limit = _MAX_ABS_INTEGER_BOUND
            elif var.kind == DecisionVariable.CONTINUOUS:
                kind = dimod.REAL
                has_continuous = True
                kind_name = "continuous"
                lower_limit = -_MAX_ABS_CONTINUOUS_BOUND
                upper_limit = _MAX_ABS_CONTINUOUS_BOUND
            else:
                raise AssertionError(
                    "Unsupported decision variable kind reached after applicability "
                    f"validation: {var.kind}. This may indicate an OMMX implementation "
                    "bug; please report it to OMMX."
                )

            bound = var.bound
            lower, upper = bound.lower, bound.upper
            if lower < lower_limit:
                raise OMMXDWaveAdapterError(
                    f"D-Wave CQM {kind_name} variable {var.id} has lower "
                    f"bound {lower}, below {lower_limit}."
                )
            if upper > upper_limit:
                raise OMMXDWaveAdapterError(
                    f"D-Wave CQM {kind_name} variable {var.id} has upper "
                    f"bound {upper}, above {upper_limit}."
                )

            self.model.add_variable(
                kind,
                var.id,
                lower_bound=lower,
                upper_bound=upper,
            )
            if kind == dimod.BINARY and lower == upper:
                # dimod ignores binary bounds, so enforce a singleton domain in the CQM.
                self.model.add_constraint_from_iterable(
                    [(var.id, 1.0)],
                    DimodSense.Eq,
                    rhs=lower,
                    label=f"fixed_binary_{var.id}",
                )
        return has_continuous

    def _set_objective(self):
        objective = self.instance.objective

        objective_degree = objective.degree()
        if objective_degree is None:
            raise AssertionError(
                "Non-polynomial objective reached after applicability validation. "
                "This may indicate an OMMX implementation bug; please report it to "
                "OMMX."
            )
        if objective_degree >= 3:
            raise AssertionError(
                "Unsupported objective degree reached after applicability validation: "
                f"{objective_degree}. This may indicate an OMMX implementation bug; "
                "please report it to OMMX."
            )

        if self.instance.sense == Instance.MINIMIZE:
            expr = self._make_expr(objective)
        elif self.instance.sense == Instance.MAXIMIZE:
            expr = self._make_expr(objective, negate=True)
        else:
            raise AssertionError(
                "Unsupported objective sense reached after applicability validation: "
                f"{self.instance.sense}. This may indicate an OMMX implementation "
                "bug; please report it to OMMX."
            )

        # Set objective function
        self.model.set_objective(expr)

    def _set_constraints(self):
        unsupported = self.instance.active_constraint_kinds - {
            ConstraintKind.Regular,
            ConstraintKind.OneHot,
        }
        if unsupported:
            raise OMMXDWaveAdapterError(
                f"Unsupported active constraint kinds: {unsupported}"
            )

        active = self.instance.active_constraints
        # Handle OneHot constraints (first-class constraint type)
        one_hot_variable_ids = set()
        selected_one_hot_constraints = []
        regularized_one_hot_constraints = []
        # Prefer constraints with more variables. The stable sort keeps the order
        # from the OneHot collection when two constraints have the same length.
        # This selection policy follows the existing ommx-da4-adapter behavior.
        sorted_one_hot_constraints = sorted(
            active.of_kind(ConstraintKind.OneHot).items(),
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
                label=str(constraint_id),
                check_overlaps=False,
            )

        for constraint_id, constraint in regularized_one_hot_constraints:
            self.model.add_constraint_from_iterable(
                ((variable_id, 1.0) for variable_id in constraint.variables),
                DimodSense.Eq,
                rhs=1.0,
                label=str(constraint_id),
            )

        for constraint_id, constraint in active.of_kind(ConstraintKind.Regular).items():
            if constraint.equality not in _DIMOD_CONSTRAINT_SENSES:
                raise AssertionError(
                    "Unsupported constraint equality reached after applicability "
                    f"validation: {constraint.equality} for constraint "
                    f"{constraint_id}. This may indicate an OMMX implementation "
                    "bug; please report it to OMMX."
                )

            constraint_degree = constraint.function.degree()
            if constraint_degree is None:
                raise AssertionError(
                    "Non-polynomial constraint reached after applicability validation: "
                    f"constraint {constraint_id}. This may indicate an OMMX "
                    "implementation bug; please report it to OMMX."
                )
            if constraint_degree >= 3:
                raise AssertionError(
                    "Unsupported constraint degree reached after applicability "
                    f"validation: {constraint_degree} for constraint {constraint_id}. "
                    "This may indicate an OMMX implementation bug; please report it "
                    "to OMMX."
                )

            # Only constant case
            if constraint_degree == 0:
                evaluated = constraint.evaluate({}, atol=ABSOLUTE_TOLERANCE)
                if evaluated.is_feasible(atol=ABSOLUTE_TOLERANCE):
                    continue
                raise OMMXDWaveAdapterError(
                    f"Infeasible constant constraint was found: id {constraint_id}"
                )

            # Create dwave expression for the constraint
            expr = self._make_expr(constraint.function)

            # rhs is assumed 0 by dwave
            self.model.add_constraint_from_iterable(
                expr,
                _DIMOD_CONSTRAINT_SENSES[constraint.equality],
                label=str(constraint_id),
            )

    def _make_expr(self, function: Function, *, negate: bool = False):
        terms = function.terms.items()
        if negate:
            return ((*ids, -coefficient) for ids, coefficient in terms)
        return ((*ids, coefficient) for ids, coefficient in terms)

    def _validate_continuous_terms(self) -> None:
        if not self.model.num_quadratic_variables(dimod.REAL, include_objective=True):
            return

        constraints = (
            (label, row.lhs) for label, row in self.model.constraints.items()
        )
        for source, expression in chain(
            [("objective", self.model.objective)], constraints
        ):
            for u, v, _ in expression.iter_quadratic():
                ids = tuple(sorted((u, v)))
                for variable_id in ids:
                    if self.model.vartype(variable_id) == dimod.REAL:
                        raise OMMXDWaveAdapterError(
                            f"D-Wave CQM only supports linear terms for continuous "
                            f"variables. The quadratic term {ids} in {source} "
                            f"contains continuous variable {variable_id}."
                        )
        raise OMMXDWaveAdapterError(
            "D-Wave CQM only supports linear terms for continuous variables."
        )
