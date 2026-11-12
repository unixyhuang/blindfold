# Blindfold 1.0 · SenSys 2026

Research artifact for *Jailbreaking Embodied LLMs via Action-Level Manipulation* by Xinyu Huang, Qiang Yang, Leming Shen, Zijing Ma, and Yuanqing Zheng. [Paper](https://doi.org/10.1145/3774906.3802758) · [BibTeX](CITATION.bib) · [Download version 1.0](https://github.com/unixyhuang/blindfold/releases/download/v1.0/blindfold-artifact.zip)

The public implementation generates household action plans with a local language model and checks them against symbolic goals. Two tabletop tasks provide explicit initial states. A supplementary run uses 100 ordinary SafeAgentBench tasks across 75 scenes. Its figures below describe that subset. Reproducing the paper's full workflow also requires its command transformation, obfuscation, and simulator components.

Version 1.0 is a rolling release. For an exact citation of the code, use the Git commit identified in the [release notes](https://github.com/unixyhuang/blindfold/releases/tag/v1.0).

## Repository layout

| Path | Contents |
| --- | --- |
| [main.py](main.py) | Command-line entry point for verification, planning, inference, and fine-tuning |
| [tasks/](tasks/) | Tabletop scenes, SafeAgentBench records, reviewed goals, and room inventories |
| [prompts/progprompt/](prompts/progprompt/) · [progprompt/](progprompt/) | Unified prompt resources, domain action generation, verifier feedback, and chain fusion |
| [verifier/](verifier/) | Action preconditions, state transitions, and goal checks |
| [finetuning/](finetuning/) · [requirements/](requirements/) | Supervised fine-tuning and model dependencies |
| [results/](results/llama31-safeagentbench-100/) | Raw model responses, verifier decisions, and run configuration |

## Quick start

The verifier runs with the Python 3.11 standard library. From a source checkout:

```sh
git clone https://github.com/unixyhuang/blindfold.git
cd blindfold
python main.py verify --task tasks/cup_to_tray.json
python main.py verify --benchmark safeagentbench
```

The tabletop command checks that the cup ends on the tray and the gripper is empty. The benchmark command checks the 100 recorded action sequences against their reviewed goals. Use `--task-id sab-safe-0085` to inspect one task or `--goals upstream` to use the original annotations. [Dataset and verification guide](tasks/safeagentbench/README.md)

To reproduce the full per-task reports from the published model responses with Python alone:

```sh
python main.py progprompt replay-benchmark --output-dir runs/replayed-safeagentbench
```

## Requirements

Local model inference and fine-tuning use Hugging Face Transformers. Create and activate a Python 3.11 virtual environment. On a compatible NVIDIA system, install the CUDA 12.6 build of PyTorch and the pinned dependencies:

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip install -r requirements/model.txt
```

For CPU inference, use the PyTorch index `https://download.pytorch.org/whl/cpu` and pass `--device cpu`. The published GPU benchmark uses 4-bit NF4 weights and the additional dependencies in [requirements/model-nf4.txt](requirements/model-nf4.txt).

## Prepare Llama-3.1

Obtain access to Meta's instruction-tuned checkpoint and download the weights, configuration, and tokenizer into one local directory. [Model card and access terms](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct)

```sh
hf auth login
hf download meta-llama/Llama-3.1-8B-Instruct --local-dir weights/Llama-3.1-8B-Instruct
python main.py infer --model weights/Llama-3.1-8B-Instruct
```

## Generate and verify plans

For a tabletop task, inspect the prompt, generate a program, and replay it in the symbolic scene:

```sh
python main.py progprompt render --task apple_to_counter
python main.py progprompt generate --task apple_to_counter --model weights/Llama-3.1-8B-Instruct --save-program runs/apple.plan
python main.py progprompt replay --task apple_to_counter --program runs/apple.plan
```

For a tabletop transfer recorded in two overlapping fragments, the reconciliation prompt proposes one event order. The verifier checks that both fragments are preserved and that the combined actions reach the goal. The same ProgPrompt module provides a read-only feedback command for an existing verifier report. [Prompt interfaces](prompts/progprompt/README.md)

For the 100-task run, prepare the pinned NF4 checkpoint using the benchmark guide, then run the batch from the repository root. Each prompt contains the instruction, action interface, demonstrations, and room object list. The verifier checks the generated actions against the reviewed goal. [NF4 setup and benchmark protocol](prompts/progprompt/safeagentbench.md)

```sh
python main.py progprompt benchmark --model weights/llama31-8b-instruct-nf4 --batch-size 10 --max-new-tokens 256 --output-dir runs/llama31-safeagentbench-100
```

## Results

Both rows use the same 100 tasks and reviewed terminal goals.

| Input to the verifier | Goal supported | Contradiction | Invalid program | Insufficient evidence |
| --- | ---: | ---: | ---: | ---: |
| Programs generated by Llama-3.1-8B-Instruct (NF4) | 39 | 26 | 24 | 11 |
| Recorded SafeAgentBench action sequences | 64 | 0 | — | 36 |

These counts measure symbolic support for the goal under the assumption that recorded actions succeed. For example, a `pour` step records a tilt but does not establish that liquid reached the intended object. The room inventories come from ALFRED's AI2-THOR 2.1.0 export, while SafeAgentBench uses 5.0.0. The task reports identify object types missing from the supplied inventories. [Run record](results/llama31-safeagentbench-100/README.md) · [Per-task findings](results/llama31-safeagentbench-100/failures.md) · [Annotation review](tasks/safeagentbench/annotation-review.md)

## Local SLM fine-tuning

The supervised training command uses the 100 household instructions and their annotated steps. It masks prompt and padding tokens and saves the trained model in Hugging Face format. Full-parameter training requires memory for weights, gradients, optimizer state, and activations. [Training guide](docs/local-slm.md)

```sh
python main.py finetune --model weights/Llama-3.1-8B-Instruct --output-dir weights/local-slm
```

## Training-free alternative

Huang et al. study inference-time generation methods in *Catastrophic Jailbreak of Open-source LLMs via Exploiting Generation*. Their repository provides the external reference implementation. [Paper](https://arxiv.org/abs/2310.06987) · [Official implementation](https://github.com/Princeton-SysML/Jailbreak_LLM)

## Citation

Cite Xinyu Huang, Qiang Yang, Leming Shen, Zijing Ma, and Yuanqing Zheng, “Jailbreaking Embodied LLMs via Action-Level Manipulation,” *SenSys 2026*, pp. 1057–1071. [BibTeX](CITATION.bib)
