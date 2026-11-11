# Blindfold · Public implementation examples

This companion to [Jailbreaking Embodied LLMs via Action-Level Manipulation](https://doi.org/10.1145/3774906.3802758) includes a runnable tabletop verifier and a local Ollama client. The verifier illustrates the precondition and effect checks in §5.4 with two household tasks. The original adversarial planner, obfuscator, refinement pipeline and platform adapters are outside this implementation.

## Run from source

Use Python 3.11 and open a terminal in the extracted directory containing `main.py`. Both examples use the Python standard library.

```sh
python main.py
python main.py verify --task assets/examples/agentsafe_apple_counter.json
```

The first command checks a record of placing an empty cup on a tray. The second checks an apple transfer. Both print JSON. On success, `status` is `passed`, `goal_met` is `true`, and `final_state.arm.held` is `null`. The object's `on` field names its destination. A rule failure exits with code 1 and lists the first failed rule. Invalid input exits with code 2. A failed placement rolls back the tentative pickup in the returned state.

## Call local llama3.1

With Ollama running locally and the `llama3.1` tag available, run:

```sh
python main.py ollama
```

The [standalone client](examples/ollama_local.py) sends a short cup-location question to `POST http://127.0.0.1:11434/api/chat` with `model` set to `llama3.1` and `stream` set to `false`. It prints `message.content` from the JSON response. Ollama manages the local weights. A refused connection means the server is unreachable at the specified address. Start the Ollama app or `ollama serve` on the model host. Use `ollama list` to check its installed tags. [Ollama chat API](https://docs.ollama.com/api/chat)

## Tasks and rules

| Input file | Task and provenance |
| --- | --- |
| [Cup and tray](assets/examples/task_bundle.json) | Original tabletop task with instruction, scene, steps and goal. Its organization draws on the [SafeAgentBench benign task records](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/main/safe_detailed.jsonl). |
| [Apple and counter](assets/examples/agentsafe_apple_counter.json) | The instruction comes from the *Normal Instructions* example in [AGENTSAFE §4.2](https://arxiv.org/html/2506.14697v3#S4.SS2). The scene, entity IDs, actions and formal goal were written for this artifact. |

Each JSON file contains the whole input. The verifier reads the recorded `actions` and the structured `scene` and `goal`. `instruction` and `provenance` document what the record represents. The included states use one gripper and a destination slot that holds one item.

| Rule | Conditions checked | State change |
| --- | --- | --- |
| Initial state | Expected entities start on their specified supports. The gripper is empty. The cup is empty or the apple is whole, and the item is at ambient temperature. | Snapshot the initial scene. |
| `inspect` | The named item is in reach or held. | Preserve the scene. |
| `pick` | The named item is on the table and within reach. The gripper is empty. | Remove the table support and set the gripper's held item. |
| `place` | The gripper holds the named item. The task's destination is reachable and its placement slot is free. | Set the new support, occupy the slot and empty the gripper. |
| Goal | The item is on the requested support, the destination is occupied and the gripper is empty. | Commit the resulting symbolic scene. |

The local rules and single-slot assumption are defined in [tabletop.py](demo/tabletop.py). These checks describe the supplied symbolic scene. Physical motion, sensing and collision checking would require a platform implementation.

## Release files

- [GitHub synchronization](docs/github-sync.md) describes the one-command local update and automatic Actions ZIP and tagged Release builds.
- [Run status](docs/run-status.md) records the observed outcomes of the two tasks and the model connection check.
- [Prompt inventory and rendering example](prompts/README.md) covers task-goal identification, final-state assessment and three record-review templates.
- [Paper implementation notes](docs/implementation.md) describe the components of the research system.
- [Optional dependency check](docs/environment-validation.md) records a separate PyTorch/Transformers CUDA smoke test. These packages are used by `scripts/check_environment.py`.
- [Citation](CITATION.bib) gives the paper reference. The source-code license is pending author selection.
