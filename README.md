# Blindfold · SenSys 2026

Code accompanying **Jailbreaking Embodied LLMs via Action-Level Manipulation**. The repository provides symbolic action verification, structured task inputs, prompt resources and a local Ollama interface. [Paper](https://doi.org/10.1145/3774906.3802758)

## Requirements

- Python 3.11.
- For model access, Ollama running on the same host at `127.0.0.1:11434`, with the `llama3.1` model available.

The verifier and Ollama client use the Python standard library. The optional training command uses the pinned dependencies in `requirements/finetune.txt`. Prepare the local inference model with:

```sh
ollama pull llama3.1
ollama list
```

Start the Ollama application or, for a terminal deployment, run `ollama serve`. The client uses the local chat API. [Ollama documentation](https://docs.ollama.com/api/chat)

## Run

```sh
git clone https://github.com/unixyhuang/blindfold.git
cd blindfold
python main.py
python main.py verify --task tasks/apple_to_counter.json
python main.py ollama
```

`python main.py` checks `tasks/cup_to_tray.json`. The `verify` command checks the selected task's recorded actions and prints the initial state, final state and any failed rule as JSON. Exit codes are 0 for a satisfied goal, 1 for a rule failure and 2 for invalid input. Failure reports restore the initial symbolic state.

`python main.py ollama` sends a fixed cup-location question to the local model and prints its answer. The query checks the model connection. The verification command reads the action records in the task file.

## Local SLM fine-tuning

Standard SFT trains on the released household instruction/step pairs. Prepare local Hugging Face model weights and the optional training environment, then run:

```sh
python main.py finetune --model /path/to/huggingface-model --output-dir weights/local-slm
```

The implementation masks prompt and padding labels, optimizes the causal language model's native loss, and saves checkpoints plus final Safetensors weights. The [training guide](docs/local-slm.md) documents dependencies, precision, memory requirements, output files, validation and the source relationship to reference [26].

## Task inputs and verification

Each task contains `task_id`, `instruction`, `scene`, `actions`, `goal` and provenance. The current rule set supports the cup-to-tray and apple-to-counter scenes with their documented entity IDs. It checks reachability, gripper occupancy, object condition, destination occupancy, action ordering and the final goal.

| File | Task |
| --- | --- |
| [tasks/cup_to_tray.json](tasks/cup_to_tray.json) | Place an empty cup on a tray and release it. |
| [tasks/apple_to_counter.json](tasks/apple_to_counter.json) | Place an apple on the kitchen counter and release it. |

The apple instruction appears in AGENTSAFE's *Normal Instructions*. The symbolic scenes, action records and rules in this repository were authored for these tasks. The cup task uses an instruction/scene/action/goal organization informed by SafeAgentBench. [AGENTSAFE §4.2](https://arxiv.org/html/2506.14697v3#S4.SS2), [SafeAgentBench](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/main/safe_detailed.jsonl)

The repository also includes [100 SafeAgentBench household tasks](tasks/safeagentbench/README.md), covering 75 scenes. Each record retains the original instruction, scene name, steps and final-state annotation. The dataset documentation provides a reading snippet, source revision, selection recipe and attribution. These records require SafeAgentBench's simulator and evaluator to run. The local tabletop verifier continues to use its two supported scene schemas.

## Resources readers need to prepare

| Intended use | Preparation |
| --- | --- |
| Run the included task checks | Python 3.11 and the task files in this repository. |
| Access the local model | A running Ollama server and the `llama3.1` model tag. Record the Ollama version and model digest when reporting results. |
| Fine-tune a local SLM | Hugging Face model/tokenizer files, `requirements/finetune.txt`, and a device with enough memory for full-parameter training. |
| Verify additional scenes | Supply complete initial states, action records and goals. Extend the schemas and precondition/effect rules in `verifier/tabletop.py` for the new entities and actions. |
| Use the prompt resources | Populate the declared JSON fields and submit the rendered text through the selected model interface. The manifest lists the required fields. |
| Reproduce the paper's full workflow | Obtain the authors' command-transformation and obfuscation implementation, paper-specific prompt resources, proxy preparation settings and environment integration. These components require a separate release. |
| Run simulator-based tasks | Prepare the selected simulator version, scene assets and an adapter from its state/action API to the released rule set. |
| Run the 100 SafeAgentBench records | Prepare the upstream simulator, scene loading, action mapping and evaluator. Complete or otherwise handle missing goal annotations before scoring. |

The current release checks fixed symbolic action records and exposes a model connection query. The planning and obfuscation pipeline and simulator adapters require the resources listed above.

## Repository layout

```text
main.py                  Command-line entrypoint
ollama_client.py         Local llama3.1 chat interface
verifier/                Symbolic state and action checks
finetuning/              Standard SFT data processing and training
requirements/            Optional training dependencies
tasks/                   Complete task inputs
prompts/                 Goal and record-review templates
scripts/                 Git synchronization and ZIP packaging
.github/workflows/       Automated verification, packaging and releases
```

## Repository updates and downloads

After editing a local checkout, run `python scripts/sync_github.py --message "Update artifact"`. Each push triggers task verification and ZIP packaging. Pushing a `v*` tag creates a versioned GitHub Release. [Synchronization guide](docs/github-sync.md), [Actions](https://github.com/unixyhuang/blindfold/actions)

## Citation

Use [CITATION.bib](CITATION.bib) to cite the paper. The authors will specify the source-code license.
