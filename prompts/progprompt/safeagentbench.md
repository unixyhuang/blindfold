# Generate and verify the 100 SafeAgentBench plans

The benchmark asks a local Llama-3.1-8B-Instruct model to write one household program for each of the 100 released tasks. Each prompt contains the task instruction, scene name, allowed actions, examples and the supported object types present in that room's inventory. The prompt builder receives only those inputs. Reference steps and reviewed goal annotations stay outside the model prompt. After generation, the interpreter converts the model's program into steps and the verifier checks those steps against the reviewed goal.

## Prepare the local model

Use the Python 3.11 virtual environment described in the [repository setup](../../README.md#requirements). The tested GPU environment used PyTorch 2.8.0 with CUDA 12.6 on an RTX 4070 Ti SUPER. Install the pinned NF4 dependencies in the activated environment, then download the checkpoint from the repository root.

```sh
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip install -r requirements/model-nf4.txt
python -m pip check
hf download unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit --revision f15c379fb32bb402fa06a7ae9aecb1febf4b79ec --local-dir weights/llama31-8b-instruct-nf4 --include model.safetensors config.json generation_config.json special_tokens_map.json tokenizer.json tokenizer_config.json README.md
```

This public Unsloth distribution uses the Llama 3.1 Community License. It preserves Meta's instruction-tuned architecture and provides NF4 weights with double quantization and bfloat16 computation. The tested environment used bitsandbytes 0.48.2. All seven downloaded files were verified against the pinned Hub metadata. The 5,702,746,383-byte Safetensors file has SHA-256 `f6c8ab7a8b2790ce56f3ae3946ad39866fc5250b51b277c9d0eee83ac4f26a92`. [Checkpoint and model card](https://huggingface.co/unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit/tree/f15c379fb32bb402fa06a7ae9aecb1febf4b79ec) · [Meta license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE)

## Run

```sh
python main.py progprompt benchmark --model weights/llama31-8b-instruct-nf4 --batch-size 10 --max-new-tokens 256 --output-dir runs/llama31-safeagentbench-100
```

The runner loads the local checkpoint once and formats each prompt with its Hugging Face chat template. The recorded run used automatic GPU placement, batches of 10, greedy decoding and a limit of 256 new tokens per task. Completed batches are saved to disk. Repeating the command with the same inputs and output directory resumes the run. To check one task, add `--task-id sab-safe-0085` and select a separate output directory.

The bundled inventory covers all 75 FloorPlans using per-room object types from ALFRED with AI2-THOR 2.1.0. SafeAgentBench uses AI2-THOR 5.0.0. A type can therefore be absent from the supplied list yet exist in the benchmark room. The lists describe object types and omit initial instance states, positions and reachability. To use inventories exported for your simulator version, pass `--inventories PATH`. Use the bundled JSON structure with a `source` entry identifying the export and an `inventories` mapping from FloorPlan names to arrays of object type names. The runner intersects each list with its supported vocabulary. [Bundled inventory and provenance](../../tasks/safeagentbench/scene_objects.json) · [Pinned ALFRED layouts](https://github.com/askforalfred/alfred/tree/f91f4c0c96c7a29f33d0557f86b0a21035379b3b/gen/layouts)

## Read the output

To reproduce the published scores without loading a model, run the offline replay command from the repository root:

```sh
python main.py progprompt replay-benchmark --output-dir runs/replayed-safeagentbench
```

The published snapshot stores the [raw completions and input hashes](../../results/llama31-safeagentbench-100/README.md), aggregate scores and the failure report. Replay checks the input fingerprints and task IDs, then rebuilds the four derived reports below in the selected output directory. A fresh model run writes all six files.

The verifier accepts a bare function or one unambiguous Python code block. Text surrounding a single block is retained in the raw response. The extracted body is checked verbatim. Multiple competing code blocks are reported as invalid. For comparison, `status_if_surrounding_prose_rejected` gives the counts under a response-format rule that also rejects explanatory prose.

| File | Contents |
| --- | --- |
| `manifest.json` | Model-file hashes, generation settings, dataset and inventory hashes, and per-task prompt hashes. |
| `completions.json` | Raw model responses indexed by task ID, saved after each batch. |
| `results.json` | Full per-task prompts, programs, generated steps, assertion checks, reviewed goals and verdicts. |
| `summary.json` | Counts by status and reason. A task with several reasons can contribute to several reason counts. |
| `not-supported.json` | Task IDs, instructions and reasons for every verdict other than `supported`. |
| `failures.md` | Human-readable listing of the affected tasks and reasons. |

`supported` means the generated steps establish the encoded goal under the symbolic rules, assuming successful actions. `contradicted` identifies a failed assertion, action precondition failure or goal mismatch. `unknown` identifies missing evidence, such as the recipient of a liquid transfer or an unobserved state needed by a guard. `invalid_program` identifies a program that cannot be interpreted, such as malformed syntax, an unlisted primitive or an object outside the room inventory. These are offline verifier outcomes. Actual task execution would require an AI2-THOR run with instance-level state observations.
