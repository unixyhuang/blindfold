# Blindfold 2.0 · SenSys 2026

Research artifact for *Jailbreaking Embodied LLMs via Action-Level Manipulation* by Xinyu Huang, Qiang Yang, Leming Shen, Zijing Ma, and Yuanqing Zheng. [Paper](https://doi.org/10.1145/3774906.3802758) · [BibTeX](CITATION.bib) · [Download version 2.0](https://github.com/unixyhuang/blindfold/releases/download/v2.0/blindfold-artifact.zip)

The public implementation generates household action plans with a local language model and checks them against symbolic goals. Bundled tabletop transfers provide explicit initial states. The supplementary SafeAgentBench adapter supports 100 ordinary tasks across 75 scenes. Version 2.0 adds the paper's action-chain prompt pipeline (command sanitization, dominant-action identification, cover branch generation, chain fusion, and planner-verifier repair) and executes the verified chain in the bundled VirtualHome Evolving Graph engine. The target embodied-LLM query, Unity rendering/physics and the real robot arm remain unimplemented.

Version 2.0 is a rolling release. For an exact citation of the code, use the Git commit identified in the [release notes](https://github.com/unixyhuang/blindfold/releases/tag/v2.0).

## What's new in 2.0

- **Action-chain prompt pipeline**: `progprompt attack` runs proxy planning → command sanitization → dominant-action identification → cover branch creation/completion → chain fusion → bounded planner-verifier repair. Every model reply is parsed as strict JSON and checked before the next stage.
- **Paper prompts as runtime templates**: the four supplied paper prompt bodies are embedded verbatim behind recorded SHA-256 digests; `check-prompts` reports a changed body as invalid.
- **Arbitrary original tasks**: `--task-file` accepts any task JSON with an instruction, scene, goal and malicious categories; `--retries` re-asks a rejected stage with the checker's reason.
- **VirtualHome execution**: `--virtualhome` compiles the verified chain into native `[FIND]`/`[GRAB]`/`[OPEN]`/`[PUTIN]`/`[PUTBACK]`/`[CLOSE]` lines, executes it in the bundled Evolving Graph engine, and observes `INSIDE`, container `CLOSED` and empty hands from the returned graph.
- **Verified local run**: Llama-3.1-8B-Instruct NF4 produced a 15-action fused chain with zero repairs; the same chain executed in VirtualHome (24 script lines, phone inside the closed oven). Evidence and commands are in the [attack workflow guide](docs/attack-workflow.md#verified-local-run).
- **Regression suite**: 135 unit tests cover planning, optimization, the chain pipeline, both verifiers, the CLI, and VirtualHome contracts.

## Repository layout

| Path | Contents |
| --- | --- |
| [main.py](main.py) | Command-line entry point for verification, planning, inference, and fine-tuning |
| [tasks/](tasks/) | Tabletop scenes, SafeAgentBench records, reviewed goals, and room inventories |
| [prompts/progprompt/](prompts/progprompt/) | Plain-text prompts, field contracts, and paper role index |
| [progprompt/](progprompt/) | Python code that renders prompts, invokes models, and checks programs |
| [verifier/](verifier/) | Action preconditions, state transitions, and goal checks for tabletop and chain tasks |
| [simulators/](simulators/) | VirtualHome HTTP client, graph bindings, ordinary and attack-chain execution, and observed-goal checks |
| [third_party/](third_party/) | Pinned VirtualHome Evolving Graph modules and their MIT license |
| [finetuning/](finetuning/) · [requirements/](requirements/) | Supervised fine-tuning and model dependencies |

## Quick start

The verifier runs with the Python 3.11 standard library. From a source checkout:

```sh
git clone https://github.com/unixyhuang/blindfold.git
cd blindfold
python main.py verify --task tasks/cup_to_tray.json
python main.py verify --benchmark safeagentbench
```

The tabletop command checks that the cup ends on the tray and the gripper is empty. The benchmark command checks the 100 recorded action sequences against their reviewed goals. Use `--task-id sab-safe-0085` to inspect one task or `--goals upstream` to use the original annotations. [Dataset and verification guide](tasks/safeagentbench/README.md)

Run the action-chain pipeline end to end without model weights, including VirtualHome execution:

```sh
python main.py progprompt attack --task phone_into_oven --recorded --virtualhome --output-dir runs/attack-recorded-vh
```

Inspect prompt availability and the implementation status of the paper components:

```sh
python main.py progprompt check-prompts
```

This check distinguishes executable templates from supplied paper-role text. Each supplied paper prompt is embedded verbatim in a runtime wrapper and reported as wired; the wrapper templates, not the source bodies, are substituted at run time. The command returns exit code 1 while the full paper pipeline is incomplete, and it lists the remaining target-query and simulator components.

## Requirements

Local model inference and fine-tuning use Hugging Face Transformers. Create and activate a Python 3.11 virtual environment. On a compatible NVIDIA system, install the CUDA 12.6 build of PyTorch and the pinned dependencies:

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip install -r requirements/model.txt
```

For CPU inference, use the PyTorch index `https://download.pytorch.org/whl/cpu` and pass `--device cpu`. The GPU benchmark adapter supports 4-bit NF4 weights with the additional dependencies in [requirements/model-nf4.txt](requirements/model-nf4.txt).

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

For a tabletop transfer recorded in two overlapping fragments, `tabletop_chain_fusion.txt` proposes one event order. The verifier checks that both fragments are preserved and that the combined actions reach the goal. The supplied `chain_fusion.txt` paper text is wrapped by `chain_fusion_runtime.txt` for the attack chain pipeline; the tabletop adapter keeps its separate event-ordering contract. The same ProgPrompt module provides a read-only feedback command for an existing verifier report. [Prompt interfaces and paper coverage](prompts/progprompt/README.md)

For the 100-task run, prepare the pinned NF4 checkpoint using the benchmark guide, then run the batch from the repository root. Each prompt contains the instruction, action interface, demonstrations, and room object list. The verifier checks the generated actions against the reviewed goal. [NF4 setup and benchmark protocol](prompts/progprompt/safeagentbench.md)

```sh
python main.py progprompt benchmark --model weights/llama31-8b-instruct-nf4 --batch-size 10 --max-new-tokens 256 --output-dir runs/llama31-safeagentbench-100
```

## Action-chain prompt pipeline

The four supplied paper-role prompts and the planner-verifier repair prompt run as one workflow on the bundled symbolic attack scene. Every reply is parsed as strict JSON and checked before the next stage, and the fused chain is replayed by the symbolic verifier:

```sh
python main.py progprompt attack --task phone_into_oven --recorded --output-dir runs/attack-recorded
python main.py progprompt attack --task phone_into_oven --model weights/llama31-8b-instruct-nf4 --output-dir runs/attack-model
python main.py progprompt attack --task-file runs/my-task.json --model weights/llama31-8b-instruct-nf4 --output-dir runs/attack-my-task
python main.py progprompt attack --task phone_into_oven --render-stage command_sanitization
```

`--recorded` replays authored reference replies; `--model` loads local weights once and runs every stage; `--responses` replays a JSON object of stage replies; `--task-file` supplies an original task outside `tasks/attack/`. Each stage is validated as strict JSON and re-asked with the checker reason up to `--retries` times. The output directory receives `attack.json`, `final-chain.json`, `final-commands.txt`, and each populated prompt with its raw reply. Add `--virtualhome` to compile the verified chain to native VirtualHome script and execute it in the bundled Evolving Graph engine; the run then also writes `virtualhome.json`. A local Llama-3.1-8B-Instruct NF4 run of the bundled task returned a verified 15-action fused chain with zero repairs, and the same chain executed in the bundled VirtualHome graph with the phone `INSIDE` the closed oven and both hands empty. The exact commands are recorded in the [attack workflow guide](docs/attack-workflow.md#verified-local-run). The bundled engine is symbolic; it does not query a victim model or exercise Unity assets, native physics, or the real robot arm.

## Execution scope

The ordinary-task workflow connects planning, equivalent action optimization, bounded verifier-feedback repair and VirtualHome verification for the three released tabletop transfers. The separate feedback-reporting and fragment-reconciliation commands remain available. The paper's action-chain prompt pipeline is dispatched from the same [workflow module](progprompt/workflow.py) and reuses the shared feedback envelope and local model client. `check-prompts` reports any paper source body that no longer matches its recorded digest. The bundled VirtualHome engine executes both ordinary transfers and verified attack chains; it is symbolic and does not replace Unity physics or a real arm.

Model generation can produce unsupported syntax or a plan that fails its goal. With `--optimize`, eligible ordinary action traces can be repaired within a fixed attempt limit. Invalid programs and failed assertions are not silently discarded. Template readiness does not guarantee that a model-generated plan will pass. [Optimization and feedback-repair contracts](docs/ordinary-workflow.md)

The verifier checks goal support under its symbolic action rules. For example, a `pour` step records a tilt but does not establish that liquid reached the intended object. Room inventories come from ALFRED's AI2-THOR 2.1.0 export, while SafeAgentBench uses 5.0.0. The benchmark command writes the model responses and per-task findings to the selected `--output-dir`. [Annotation review](tasks/safeagentbench/annotation-review.md)

## VirtualHome

The bundled VirtualHome Evolving Graph backend executes all three task contracts with the official graph engine and requires only Python 3.11. The ordinary optimizer preserves successful trace outcomes and uses exact verifier feedback for bounded action repair. Run without model weights using recorded actions:

```sh
python main.py virtualhome run --backend evolving-graph --task cup_to_tray --recorded --optimize --max-repairs 2 --output-dir runs/ordinary-cup-tray
```

Replace `--recorded` with `--model weights/llama31-8b-instruct-nf4` for local model planning. The [workflow guide](docs/ordinary-workflow.md) covers all three tasks, action inputs, repair boundaries and audit outputs.

The same engine executes a verified attack chain through `progprompt attack --virtualhome`. The adapter in [simulators/attack_graph.py](simulators/attack_graph.py) builds the authored phone/oven graph, compiles each chain step to native VirtualHome lines, and independently observes `INSIDE`, container `CLOSED` and empty hands. The [attack workflow guide](docs/attack-workflow.md) records the mapping, the verified 24-line run, and the remaining Unity/real-arm gap.

The Unity backend connects the same ordinary workflow to a separately running native simulator. It resolves actual graph object IDs, sends one script line at a time, and checks placement and empty hands in the returned graph. Unity execution requires an appropriate executable and scene assets. [Unity setup, bindings, and execution guide](docs/virtualhome.md)

```sh
python main.py virtualhome inspect --environment 0 --output runs/virtualhome-scene.json
python main.py virtualhome run --backend unity --task cup_to_counter --model weights/llama31-8b-instruct-nf4 --optimize --max-repairs 2 --environment 0 --bindings runs/cup-bindings.json --output-dir runs/virtualhome-model
```

Graph-backend results establish symbolic transitions; Unity assets, geometry and navigation need native validation. The SafeAgentBench collection uses AI2-THOR scenes and is not a VirtualHome task collection. This ordinary-task workflow is separate from the paper's action-chain pipeline; the [attack workflow guide](docs/attack-workflow.md) documents the chain reproduction and its VirtualHome execution, while the target-model query and Unity/real-arm validation remain open.

## Local SLM fine-tuning

The supervised training command uses the 100 household instructions and their annotated steps. It masks prompt and padding tokens and saves the trained model in Hugging Face format. Full-parameter training requires memory for weights, gradients, optimizer state, and activations. [Training guide](docs/local-slm.md)

```sh
python main.py finetune --model weights/Llama-3.1-8B-Instruct --output-dir weights/local-slm
```

## Training-free alternative

Huang et al. study inference-time generation methods in *Catastrophic Jailbreak of Open-source LLMs via Exploiting Generation*. Their repository provides the external reference implementation. [Paper](https://arxiv.org/abs/2310.06987) · [Official implementation](https://github.com/Princeton-SysML/Jailbreak_LLM)

## Citation

Cite Xinyu Huang, Qiang Yang, Leming Shen, Zijing Ma, and Yuanqing Zheng, “Jailbreaking Embodied LLMs via Action-Level Manipulation,” *SenSys 2026*, pp. 1057–1071. [BibTeX](CITATION.bib)
