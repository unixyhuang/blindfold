# Optional Transformers environment

`python main.py` and the Ollama client use the Python standard library. The pins below belong to the earlier standalone `scripts/check_environment.py` test. They passed a fresh Windows installation and CPU/CUDA tiny-model checks.

| Component | Selected version | Role |
| --- | --- | --- |
| Python | 3.11.x | Interpreter; use a maintained patch release and record the exact patch in the final environment manifest |
| PyTorch | 2.8.0 | Local inference; choose CUDA 12.6 or CPU wheel explicitly |
| Transformers | 4.57.6 | Model/tokenizer loading and generation, using the v4 API |
| Accelerate | 1.12.0 | Device mapping/model loading support |
| Tokenizers | 0.22.2 | Fast tokenizer runtime |
| Hugging Face Hub | 0.36.0 | Model retrieval/cache; within Transformers' `<1.0` constraint |
| Safetensors | 0.7.0 | Weight loading |
| NumPy | 1.26.4 | Selected array-library baseline |
| xArm Python SDK | 1.18.4, optional | Separate device adapter; firmware and camera integration still need checking |

`core.txt` pins the selected direct/critical packages. It is **not a complete transitive lock**: dependencies such as requests, Jinja2, packaging, NetworkX and NVIDIA runtime libraries are resolved by pip. The successful Windows CUDA installation is captured in [lock-windows-py311-cu126.txt](lock-windows-py311-cu126.txt), containing exact URLs and SHA256 hashes for 26 runtime wheels. It is platform-specific; do not apply it to Linux or the CPU-only profile. [Observed versions](validated-windows-py311-cu126.freeze.txt) are also supplied.

## Install the dependency environment

The validated dependency target is Windows x86-64 with Python 3.11.13, an RTX 4070 Ti SUPER and NVIDIA driver 610.88. Linux x86-64 / Ubuntu 22.04 with Python 3.11 remains a proposed, untested target. This is dependency validation, not end-to-end implementation support or a reconstruction of the paper host.

Create the environment with a Python 3.11 interpreter. From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell, with Python 3.11 installed:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Choose exactly one wheel profile, then install the shared packages:

```bash
# NVIDIA GPU: selected CUDA 12.6 wheel profile
python -m pip install -r requirements/torch-cu126.txt
python -m pip install -r requirements/core.txt
python -m pip check
```

Or, in a separate fresh environment:

```bash
# CPU: environment/import checks; 8B model memory and latency are separate concerns
python -m pip install -r requirements/torch-cpu.txt
python -m pip install -r requirements/core.txt
python -m pip check
```

For CUDA wheels, use a supported NVIDIA GPU and compatible driver. A conservative Linux baseline for the selected CUDA 12.6 build is driver **560.28.03 or newer**, derived from the CUDA 12.6 GA toolkit driver table; this is not a claim that every GPU works with that driver or wheel. Newer GPU architectures may require a different CUDA wheel profile. The system CUDA toolkit need not match the wheel label when using prebuilt PyTorch binaries without custom extensions; the host driver still must be compatible. Do not add flash-attn or other compiled extensions to this baseline without rechecking the toolchain.

The CUDA wheel profile and core installation sequence above were executed successfully using the isolated Windows interpreter. The separate CPU-only profile has not been installed. No global Python environment was modified. The public examples have a separate [main.py entrypoint](../README.md). For exact Windows reinstallation and the smoke-check command, see [validation instructions](../docs/environment-validation.md).

## Optional xArm dependency

```bash
python -m pip install -r requirements/xarm.txt
```

This pins the SDK only. No robot is connected by this command. Camera models are unspecified in the paper, so no camera SDK is selected. Check the actual firmware/API use when the original adapter code is supplied.

## VirtualHome decision

**No `virtualhome.txt` is provided yet.** PyPI's `virtualhome==2.3.0` metadata pins `networkx==2.3`, an old OpenCV build, and other legacy dependencies. NetworkX 2.3 imports `fractions.gcd`, which was removed from Python 3.9. Thus a metadata-compatible installation would still fail at runtime on this Python 3.11 baseline. The repository's current setup metadata also differs from the published wheel metadata, so a version label alone does not identify identical dependencies.

Keep simulator integration out of the core environment. When the actual VirtualHome/ProgPrompt adapter and simulator build are supplied, select a specific source revision with validated compatibility changes or a separately validated legacy environment. Do not bypass dependencies with `--no-deps` and describe the result as validated. The Unity simulator build must be selected separately from the Python client package.

## Validation and sources

See [runtime validation](../docs/environment-validation.md), [dependency decisions](../docs/dependency-versions.md) and the earlier [metadata evidence](metadata-evidence.json). pip resolution, installation, `pip check`, package imports, fast tokenization, NumPy interoperability, Safetensors/Accelerate loading, and tiny Llama CPU/CUDA generation all passed on the Windows host. The model is random and local; Llama-3.1-8B and the paper implementation were not loaded.

The Windows dependency lock and validation script are now supplied. After integrating source or changing the OS, GPU, Python or dependencies, rerun installation and `scripts/check_environment.py`, then validate the real implementation before updating platform support claims. The xArm package and firmware remain outside the core validation.
