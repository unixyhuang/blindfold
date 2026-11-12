# Blindfold · SenSys 2026

Code accompanying **Jailbreaking Embodied LLMs via Action-Level Manipulation**. The repository provides symbolic action verification, structured task inputs, prompt resources, Hugging Face inference and standard local SLM fine-tuning. [Paper](https://doi.org/10.1145/3774906.3802758)

## Repository layout

```text
main.py                  Command-line entrypoint
hf_client.py             Local Hugging Face inference for Llama-3.1
verifier/                Symbolic state and action checks
finetuning/              Standard SFT data processing and training
requirements/model.txt   Shared inference and training dependencies
tasks/                   Complete task inputs and 100 SafeAgentBench records
prompts/                 Goal and record-review templates
docs/                    Model training and repository maintenance guides
scripts/                 Git synchronization and ZIP packaging
.github/workflows/       Automated verification, model checks and releases
```

## Requirements

- Python 3.11.
- For inference and training, the pinned dependencies in `requirements/model.txt` and a local Hugging Face model/tokenizer directory.

The verifier uses the Python standard library. Prepare the model environment in a checkout:

```sh
git clone https://github.com/unixyhuang/blindfold.git
cd blindfold
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux or `.\.venv\Scripts\Activate.ps1` in Windows PowerShell. For a compatible NVIDIA GPU and driver:

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip install -r requirements/model.txt
python -m pip check
```

For CPU use, replace the PyTorch index URL with `https://download.pytorch.org/whl/cpu`.

## Prepare Llama-3.1

Obtain access to [Meta's Llama-3.1-8B-Instruct checkpoint](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct) under its model license, then download the Hugging Face files:

```sh
hf auth login
hf download meta-llama/Llama-3.1-8B-Instruct --local-dir weights/Llama-3.1-8B-Instruct
```

Keep `config.json`, all Safetensors shards and their index, the tokenizer files and the supplied generation configuration together. Record the downloaded model revision when reporting results. Both model commands load the local directory with `local_files_only=True` and `trust_remote_code=False`.

Automatic inference placement uses available GPU/CPU memory and the checkpoint's dtype. An 8B checkpoint in bfloat16 needs roughly 16 GB for weights plus runtime memory; prepare additional host/device memory for generation and offloading. `--device cpu` uses float32, which needs roughly 32 GB for weights plus runtime memory. [Hugging Face model loading](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/model#large-model-loading)

## Run

```sh
python main.py
python main.py verify --task tasks/apple_to_counter.json
python main.py infer --model weights/Llama-3.1-8B-Instruct
```

`python main.py` checks `tasks/cup_to_tray.json`. For the two tabletop tasks, `verify` prints the initial state, final state and any failed rule as JSON. Exit codes are 0 for a satisfied tabletop goal, 1 for a rule failure and 2 for invalid input. Failure reports restore the initial symbolic state.

`infer` loads `AutoTokenizer` and `AutoModelForCausalLM`, applies the tokenizer's chat template and answers a fixed cup-location question using greedy decoding. It prints only the generated answer, without the input prompt. `--max-new-tokens` defaults to 32; `--device cpu` selects CPU execution. Tokenizers without a chat template use the same user/assistant text boundary as the SFT loader. The query checks local model loading and generation. The verification command reads the action records in the task file.

## Local SLM fine-tuning

Standard SFT trains on the released household instruction/step pairs using the same model environment:

```sh
python main.py finetune --model weights/Llama-3.1-8B-Instruct --output-dir weights/local-slm
python main.py infer --model weights/local-slm/final
```

The implementation masks prompt and padding labels, optimizes the causal language model's native loss, and saves checkpoints plus final Safetensors weights. Prepare memory for full-parameter training before launching an 8B run. The [training guide](docs/local-slm.md) documents precision, memory requirements, output files, validation and the source relationship to reference [26].

## Training-free alternative

As an alternative research approach to local SLM fine-tuning, [*Catastrophic Jailbreak of Open-source LLMs via Exploiting Generation*](https://arxiv.org/abs/2310.06987) studies generation-based methods without updating model weights. For the original implementation and reproduction instructions, refer to the authors' official repository: [Princeton-SysML/Jailbreak_LLM](https://github.com/Princeton-SysML/Jailbreak_LLM).

## Task inputs and verification

The two tabletop tasks contain `task_id`, `instruction`, `scene`, `actions`, `goal` and provenance. Their verifier checks reachability, gripper occupancy, object condition, destination occupancy, action ordering and the final goal.

| File | Task |
| --- | --- |
| [tasks/cup_to_tray.json](tasks/cup_to_tray.json) | Place an empty cup on a tray and release it. |
| [tasks/apple_to_counter.json](tasks/apple_to_counter.json) | Place an apple on the kitchen counter and release it. |

The apple instruction appears in AGENTSAFE's *Normal Instructions*. The symbolic scenes, action records and rules in this repository were authored for these tasks. The cup task uses an instruction/scene/action/goal organization informed by SafeAgentBench. [AGENTSAFE §4.2](https://arxiv.org/html/2506.14697v3#S4.SS2), [SafeAgentBench](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/main/safe_detailed.jsonl)

The SafeAgentBench verifier covers all 100 recorded tasks across 75 FloorPlans. It checks action ordering, hand occupancy, placement, container state and annotated goals using Python's standard library. Select a task, a scene, or the entire collection:

```sh
python main.py verify --benchmark safeagentbench --task-id sab-safe-0085
python main.py verify --benchmark safeagentbench --scene FloorPlan203
python main.py verify --benchmark safeagentbench
```

The default verifier uses reviewed goals for all 100 records. It supports 64 intended outcomes from the recorded actions, finds 36 with insufficient evidence and reports zero contradictions. The review adds 65 goals derived from the instructions and corrects the final cabinet state in `sab-safe-0122`. Pass `--goals upstream` to repeat the check with the original annotations, or `--metadata final-event.json` with one task ID to check observed object states. [Annotation review](tasks/safeagentbench/annotation-review.md) · [Verification guide](tasks/safeagentbench/README.md#verify-the-records)

## Resources to prepare

| Intended use | Preparation |
| --- | --- |
| Run the included task checks | Python 3.11 and the task files in this repository. |
| Access the local model | Llama-3.1 Hugging Face weights and tokenizer, model access approval, `requirements/model.txt` and sufficient GPU/host memory. Record the model revision. |
| Fine-tune a local SLM | The same model environment and enough memory for parameters, gradients, optimizer state and activations during full-parameter training. |
| Check additional records | Supply a single SafeAgentBench JSON record using the documented vocabulary, or a supported tabletop task, to `verify --task PATH`. |
| Use the prompt resources | Populate the declared JSON fields and submit the rendered text through the selected model interface. The manifest lists the required fields. |
| Reproduce the paper's full workflow | Obtain the authors' command-transformation and obfuscation implementation, paper-specific prompt resources, proxy preparation settings and environment integration. These components require a separate release. |
| Run simulator-based tasks | Prepare the selected simulator version, scene assets and an adapter from its state/action API to the released rule set. |
| Check the 100 SafeAgentBench records offline | Use the bundled collection with Python 3.11. For an observed goal check, supply final event metadata from the selected task's simulator run. |

The current release checks fixed symbolic action records and provides ordinary model inference and SFT. The planning and obfuscation pipeline and simulator adapters require the resources listed above.

## Citation

Use [CITATION.bib](CITATION.bib) to cite the paper. The authors will specify the source-code license.
