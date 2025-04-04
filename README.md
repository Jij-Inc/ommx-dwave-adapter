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
from ommx.v1 import Instance, DecisionVariable

x1 = DecisionVariable.integer(1, lower=0, upper=5)
ommx_instance = Instance.from_components(
    decision_variables=[x1],
    objective=x1,
    constraints=[],
    sense=Instance.MINIMIZE,
)

# Create `ommx.v1.SampleSet` through `diwave.system.LeapHybridCQMSampler`
# Your Leap token can be set through configuration file, environment variable,
# or passed with a `token` parameter.
ommx_sampleset = OMMLeapHybridCQMAdapter.sample(ommx_instance)

print(ommx_sampleset)
```
