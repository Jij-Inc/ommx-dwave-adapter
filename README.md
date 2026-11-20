# ommx-dwave-adapter

Provides an adapter to translate between [OMMX](https://github.com/Jij-Inc/ommx) and [D-Wave](https://docs.ocean.dwavesys.com/en/stable/index.html) samplers.

Currently only implements an adapter to LeapHybridCQMSampler.

Requires Python 3.11 or later and OMMX SDK `>=3.0.0rc1,<4`.

Continuous variables can appear in linear terms. The adapter rejects quadratic
terms involving a continuous variable when converting the objective or an
active constraint to a D-Wave CQM, including constraints produced by preparation.

# Usage

`ommx-dwave-adapter` can be installed from PyPI as follows:

```bash
pip install ommx-dwave-adapter
```

An example usage of the LeapHybridCQMSampler through this adapter:

```python
from ommx_dwave_adapter import OMMXLeapHybridCQMAdapter
from ommx import Instance

ommx_instance = Instance.minimize()
x1 = ommx_instance.new_binary("x1")
ommx_instance.objective = x1

# Create `ommx.SampleSet` through `dwave.system.LeapHybridCQMSampler`
# Your Leap token can be set through configuration file, environment variable,
# or passed with a `token` parameter.
ommx_sampleset = OMMXLeapHybridCQMAdapter.sample(ommx_instance)

print(ommx_sampleset)
```

When accessing the dimod model through `sampler_input`, use the integer OMMX
variable ID as the variable label and `str(constraint_id)` as the constraint
label (for example, `"ConstraintID(7)"` or `"OneHotConstraintID(2)"`).
For an active binary variable with equal lower and upper bounds, the adapter
adds an equality labeled `fixed_binary_<variable ID>` to enforce the fixed value.
