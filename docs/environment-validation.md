# Core dependency installation validation

Checked on 2026-11-11 in a fresh virtual environment, with system site-packages disabled. The global Python environment was not modified. No original source code or external model weights were installed.

## Result

**PASS. All seven selected core package versions installed unchanged.** pip reported `No broken requirements found.` No version adjustment was required.

| Host detail | Actual value |
| --- | --- |
| OS / architecture | Windows / x86-64 (AMD64) |
| Interpreter | Python 3.11.13 |
| Installer | pip 24.0 |
| PyTorch | 2.8.0+cu126 |
| CUDA runtime reported by PyTorch | 12.6 |
| GPU | NVIDIA GeForce RTX 4070 Ti SUPER |
| NVIDIA driver | 610.88 |

Installed direct pins: Transformers 4.57.6, Accelerate 1.12.0, Tokenizers 0.22.2, Hugging Face Hub 0.36.0, Safetensors 0.7.0 and NumPy 1.26.4, alongside PyTorch above.

## Checks actually executed

| Check | Result |
| --- | --- |
| Fresh installation from the PyTorch CUDA 12.6 index, then PyPI | PASS |
| Expected package versions and `pip check` | PASS |
| Imports of all seven core packages | PASS |
| NumPy / PyTorch array round-trip | PASS |
| Locally constructed fast tokenizer and Jinja chat template | PASS |
| Tiny randomly initialized Llama: CPU SDPA forward pass and generation | PASS |
| Safetensors save/reload with Accelerate-backed device mapping | PASS |
| Reloaded tiny Llama: CUDA FP16 SDPA forward pass and generation | PASS |

The tiny model has two layers, hidden size 32 and a local eight-token vocabulary. It is built from configuration and saved/reloaded locally. No Hugging Face model download, API key or paid service is needed. These checks establish basic runtime interoperability, not full-model accuracy, memory feasibility or Blindfold functionality.

Machine-readable results: [environment-validation.json](environment-validation.json). Exact installed artifact URLs/hashes: [installed-wheel-provenance.json](installed-wheel-provenance.json).

## Reuse the verified dependency environment

From the repository root on Windows x86-64 with Python 3.11 and a compatible NVIDIA GPU/driver:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated install -r requirements/lock-windows-py311-cu126.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/check_environment.py --require-cuda --output runs/environment-validation.json
```

The lock lists the exact 26 installed wheels with SHA256 hashes, including transitive dependencies. `--no-index` disables index discovery; **internet is still required** to fetch its explicit wheel URLs unless those wheels are already available locally. pip/setuptools bootstrap packages and the Python interpreter are not part of this runtime wheel lock. The lock was generated from successful installation reports and checked against the installed package inventory; it was not separately installed in a second environment.

## Limits

Linux/Ubuntu installation, the separate CPU-only torch wheel, full Llama-3.1-8B weights, original Blindfold source, VirtualHome and xArm/cameras were not validated. CPU computation was checked using the installed CUDA-enabled PyTorch build. Do not describe this result as Linux support or end-to-end paper implementation validation.

The initial venv bootstrap hit the desktop sandbox's temporary-directory permission restriction. Pointing the process-local TEMP/TMP directories at workspace scratch storage resolved it; this was an environment setup issue, not a package conflict.
