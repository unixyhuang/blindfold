# Dependency selection and evidence

Selection prepared on 2026-11-11 for a new implementation release. The original source/environment has not been supplied. These pins select a candidate backend; they do not establish the software used in the paper.

## Choice

Use Python 3.11.x, PyTorch 2.8.0, Transformers 4.57.6, Accelerate 1.12.0, Tokenizers 0.22.2, Hugging Face Hub 0.36.0, Safetensors 0.7.0 and NumPy 1.26.4. The default GPU installation profile selects `torch==2.8.0+cu126`. A CPU profile is supplied separately. Retaining the Transformers v4 API is a packaging choice to reduce migration work when incorporating older source.

Meta's [Llama 3.1 model card](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct) documents Transformers-based loading. This supports choosing that backend, but does not resolve which base/instruct variant or prepared checkpoint the original code used.

## Compatibility evidence

| Check | Published constraint | Selected value |
| --- | --- | --- |
| Transformers -> Hub | `>=0.34.0,<1.0` | 0.36.0 |
| Transformers -> Tokenizers | `>=0.22.0,<=0.23.0` | 0.22.2 |
| Transformers -> Safetensors | `>=0.4.3` | 0.7.0 |
| Transformers `[torch]` -> PyTorch | `>=2.2` | 2.8.0 |
| Accelerate -> PyTorch | `>=2.0.0` | 2.8.0 |
| Accelerate -> Hub | `>=0.21.0` | 0.36.0 |
| Accelerate -> Safetensors | `>=0.4.3` | 0.7.0 |
| Accelerate -> Python | `>=3.10.0` | 3.11.x |

The remaining selected pins also accept Python 3.11 according to their metadata. This checks published constraints between selected packages, not every transitive dependency or model-generation behavior. Subsequent fresh Windows installation, `pip check`, imports, fast tokenization and tiny Llama CPU/CUDA generation all passed without changing these pins. See the [runtime validation report](environment-validation.md). Linux and the full implementation remain unvalidated.

Authoritative sources:

- [PyTorch 2.8.0 official wheel commands](https://pytorch.org/get-started/previous-versions/#v280)
- [Transformers 4.57.6 metadata](https://pypi.org/pypi/transformers/4.57.6/json)
- [Accelerate 1.12.0 metadata](https://pypi.org/pypi/accelerate/1.12.0/json)
- [Tokenizers 0.22.2 metadata](https://pypi.org/pypi/tokenizers/0.22.2/json)
- [Hub 0.36.0 metadata](https://pypi.org/pypi/huggingface-hub/0.36.0/json)
- [Safetensors 0.7.0 metadata](https://pypi.org/pypi/safetensors/0.7.0/json)
- [NumPy 1.26.4 metadata](https://pypi.org/pypi/numpy/1.26.4/json)
- [CUDA 12.6 driver table](https://docs.nvidia.com/cuda/archive/12.6.0/cuda-toolkit-release-notes/index.html)

## Optional components

The [xArm SDK 1.18.4 metadata](https://pypi.org/pypi/xarm-python-sdk/1.18.4/json) accepts Python >=3.5. This is an optional SDK pin, with firmware compatibility and camera dependencies still pending actual adapter inputs.

VirtualHome remains unresolved deliberately: the [published 2.3.0 metadata](https://pypi.org/pypi/virtualhome/2.3.0/json) pins NetworkX 2.3. Its [source imports `fractions.gcd`](https://github.com/networkx/networkx/blob/networkx-2.3/networkx/algorithms/dag.py), which [Python 3.9 removed](https://docs.python.org/3.9/whatsnew/3.9.html#removed). This gives a concrete runtime incompatibility with Python 3.11 that a package resolver alone will not catch. The [VirtualHome repository setup file](https://github.com/xavierpuigf/virtualhome/blob/master/setup.py) also differs from its published package metadata. A simulator/client revision and real source are needed before selecting a compatible isolated adapter environment.

No vLLM, PEFT, bitsandbytes, flash-attn, datasets, or camera SDK is selected: the current implementation proposal does not establish a need for them. Add such dependencies only if the actual backend, checkpoint preparation or adapter imports require them.
