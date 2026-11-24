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
