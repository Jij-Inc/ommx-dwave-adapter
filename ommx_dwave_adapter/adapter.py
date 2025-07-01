from ommx.adapter import SamplerAdapter
from ommx.v1 import (
    Instance,
    DecisionVariable,
    Constraint,
    Function,
    Solution,
    SampleSet,
)

import math
import dimod
from dimod import ConstrainedQuadraticModel
from dwave.system import LeapHybridCQMSampler
from typing import Optional

from .exception import OMMXDWaveAdapterError

ABSOLUTE_TOLERANCE = 1e-6


class OMMXLeapHybridCQMAdapter(SamplerAdapter):
    def __init__(self, ommx_instance: Instance):
        """
        :param ommx_instance: The ommx.v1.Instance to sample.
        """
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
    ) -> SampleSet:
        """Solve the given ommx.v1.Instance using dwave's LeapHybridCQMSampler,
        returning the samples as an ommx.v1.SampleSet.

        **NOTE** The `token` must be specified either through the optional
          parameter or the DWave config file. Refer to DWave documentation for
          more info.

        :param ommx_instance: The ommx.v1.Instance to solve.
        :param token: Token for instantiating the DWave sampler, obtained from your Leap account.
        :param time_limit: Maximum time the solver will use, in seconds. Must be greater than the minimum time limit specified by DWave (currently 5)
        :param label: Optional label to tag the problem with.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx.v1 import Instance, DecisionVariable, Linear
            >>>
            >>> x1 = DecisionVariable.integer(1, lower=0, upper=5)
            >>> ommx_instance = Instance.from_components(
            ...     decision_variables=[x1],
            ...     objective=x1,
            ...     constraints=[],
            ...     sense=Instance.MINIMIZE,
            ... )
            >>> token = "YOUR API TOKEN" # Set your API token
            >>> solution = OMMXFixstarsAmplifyAdapter.sample(ommx_instance, token=token) # doctest: +SKIP
        """
        # Dwave appears to be able to read configuration from a config file
        # automatically, and this apparently includes the token. Users may want
        # to use the file as a way to pass the token, so we can't necessarily
        # give an error on an empty token

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
    ) -> Solution:
        """Solve the given ommx.v1.Instance using dwave's LeapHybridCQMSampler,
        returning the best feasible solution as an ommx.v1.Solution.

        **NOTE** The `token` must be specified either through the optional
          parameter or the DWave config file. Refer to DWave documentation for
          more info.

        :param ommx_instance: The ommx.v1.Instance to solve.
        :param token: Token for instantiating the DWave sampler, obtained from your Leap account.
        :param time_limit: Maximum time the solver will use, in seconds. Must be greater than the minimum time limit specified by DWave (currently 5)
        :param label: Optional label to tag the problem with.

        Example:
        =========
        The following example shows how to solve an unconstrained linear optimization problem with `x` as the objective function.

        .. doctest::

            >>> from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
            >>> from ommx.v1 import Instance, DecisionVariable, Linear
            >>>
            >>> x1 = DecisionVariable.integer(1, lower=0, upper=5)
            >>> ommx_instance = Instance.from_components(
            ...     decision_variables=[x1],
            ...     objective=x1,
            ...     constraints=[],
            ...     sense=Instance.MINIMIZE,
            ... )
            >>> token = "YOUR API TOKEN" # Set your API token
            >>> solution = OMMXFixstarsAmplifyAdapter.solve(ommx_instance, token=token) # doctest: +SKIP
        """
        return cls.sample(
            ommx_instance, token=token, time_limit=time_limit, label=label
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
        """Convert a dimod.SampleSet model matching this instance to an ommx.v1.SampleSet.

        This method is intended to be used if the model has been acquired with
        `sampler_input` for futher adjustment of the sampler parameters, and
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
            >>> from ommx.v1 import Instance, DecisionVariable, Linear
            >>> from dwave.system import LeapHybridCQMSampler
            >>> x1 = DecisionVariable.integer(1, lower=0, upper=5)
            >>> ommx_instance = Instance.from_components(
            ...     decision_variables=[x1],
            ...     objective=x1,
            ...     constraints=[],
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
        """Convert a dimod.SampleSet model matching this instance to an ommx.v1.Solution."""
        sample_set = self.decode_to_sampleset(data)
        return sample_set.best_feasible

    def _set_decision_variables(self):
        for var in self.instance.decision_variables:
            if var.kind == DecisionVariable.BINARY:
                self.model.add_variable("BINARY", var.id)
            elif var.kind == DecisionVariable.INTEGER:
                self.model.add_variable(
                    "INTEGER",
                    var.id,
                    lower_bound=var.bound.lower,
                    upper_bound=var.bound.upper,
                )
            elif var.kind == DecisionVariable.CONTINUOUS:
                self.model.add_variable(
                    "REAL",
                    var.id,
                    lower_bound=var.bound.lower,
                    upper_bound=var.bound.upper,
                )
            else:
                raise OMMXDWaveAdapterError(
                    f"Unsupported decision variable kind: "
                    f"id: {var.id}, kind: {var.kind}"
                )

    def _set_objective(self):
        objective = self.instance.objective

        # Check if objective function is non linear
        if objective.degree() >= 3:
            raise OMMXDWaveAdapterError(
                "Unsupported objective function type: must be either `constant`, `linear` or `quadratic`."
            )

        expr = self._make_expr(objective)

        if self.instance.sense == Instance.MAXIMIZE:
            # multiply all coefficients by -1:
            # this takes all except the last element from the tuple and concatenates it
            # with the last element multiplied with -1 to get a new tuple
            expr = [tuple[:-1] + (-1 * tuple[-1],) for tuple in expr]

        # Set objective function
        self.model.set_objective(expr)

    def _set_constraints(self):
        for constraint in self.instance.constraints:
            # Check if the constraints is non linear
            if constraint.function.degree() >= 3:
                raise OMMXDWaveAdapterError(
                    f"Constraints must be either `constant`, `linear` or `quadratic`."
                    f"id: {constraint.id}, "
                )

            # Only constant case
            if constraint.function.degree() == 0:
                if constraint.equality == Constraint.EQUAL_TO_ZERO and math.isclose(
                    constraint.function.constant_term, 0, abs_tol=ABSOLUTE_TOLERANCE
                ):
                    continue
                elif (
                    constraint.equality == Constraint.LESS_THAN_OR_EQUAL_TO_ZERO
                    and constraint.function.constant_term <= ABSOLUTE_TOLERANCE
                ):
                    continue
                else:
                    raise OMMXDWaveAdapterError(
                        f"Infeasible constant constraint was found: id {constraint.id}"
                    )

            # Create dwave expression for the constraint
            expr = self._make_expr(constraint.function)

            if constraint.equality == Constraint.EQUAL_TO_ZERO:
                constr_sense = "=="
            elif constraint.equality == Constraint.LESS_THAN_OR_EQUAL_TO_ZERO:
                constr_sense = "<="
            else:
                raise OMMXDWaveAdapterError(
                    f"Unsupported constraint equality: "
                    f"id: {constraint.id}, equality: {constraint.equality}"
                )

            # rhs is assumed 0 by dwave
            self.model.add_constraint_from_iterable(
                expr, constr_sense, label=constraint.id
            )

    def _make_expr(self, function: Function):
        """Create a dwave expression from an OMMX Function."""
        expr = []
        for ids, coefficient in function.terms.items():
            expr.append((*ids, coefficient))

        return expr
