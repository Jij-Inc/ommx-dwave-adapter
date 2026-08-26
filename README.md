# ommx-dwave-adapter

Provides an adapter to translate between [OMMX](https://github.com/Jij-Inc/ommx) and [D-Wave](https://docs.ocean.dwavesys.com/en/stable/index.html) samplers.

Currently only implements an adapter to LeapHybridCQMSampler.

# Usage

`ommx-dwave-adapter` can be installed from PyPI as follows:

```bash
pip install ommx-dwave-adapter
```

An example usage of the LeapHybridCQMSampler through this adapter:

```python
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
from ommx import Instance, DecisionVariable

x1 = DecisionVariable.integer(1, lower=0, upper=5)
ommx_instance = Instance.from_components(
    decision_variables=[x1],
    objective=x1,
    constraints={},
    sense=Instance.MINIMIZE,
)

# Create `ommx.SampleSet` through `dwave.system.LeapHybridCQMSampler`
# Your Leap token can be set through configuration file, environment variable,
# or passed with a `token` parameter.
ommx_sampleset = OMMXLeapHybridCQMAdapter.sample(ommx_instance)

print(ommx_sampleset)
```

`sample()` and `solve()` do not modify the input `Instance`. They prepare an
isolated copy with `recommended_preparation_policy()` before calling the
preparation-free execution path. `sample()` returns an `ommx.SampleSet`, while
`solve()` returns its best feasible `ommx.Solution`.

## Explicit preparation

Prepare the instance explicitly when you need to customize the preparation
policy or inspect the exact Adapter input. Pass the prepared instance to
`sample_without_preparation()` or `solve_without_preparation()`:

```python
import copy

from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter

prepared = copy.copy(ommx_instance)
prepared.prepare(
    OMMXLeapHybridCQMAdapter.INPUT_CLASS,
    OMMXLeapHybridCQMAdapter.recommended_preparation_policy(),
)

ommx_sampleset = OMMXLeapHybridCQMAdapter.sample_without_preparation(prepared)
```

The preparation-free methods require an exact `INPUT_CLASS` member and never
prepare it automatically. The prepared `Instance` remains responsible for
restoring source-variable values and evaluating constraints removed during
preparation.
