# Local ProgPrompt

This implementation reproduces the prompt structure described by Singh et al. for two symbolic tabletop transfers. The upstream evaluation uses GPT completions and a VirtualHome Unity scene. Here the repository supplies a complete tabletop state and a local Hugging Face checkpoint supplies the completion. For SafeAgentBench, a separate batch command uses independently exported object-type inventories for 75 named rooms. [100-task batch guide](safeagentbench.md) · [Authors' project](https://progprompt.github.io/) · [Official VirtualHome implementation and setup](https://github.com/NVlabs/progprompt-vh)

| Prompt file | Contribution |
| --- | --- |
| [header.txt](header.txt) | Declares action signatures, state predicates and the permitted program syntax. |
| [demonstrations.txt](demonstrations.txt) | Three independently written task functions illustrate subgoal comments, direct actions, assertions and conditional recovery. |
| [query.txt](query.txt) | Inserts the current scene's object IDs, initial state, instruction and a function header derived from the task description. |

The renderer reads the task's instruction and initial scene. The scene's action schema supplies the valid item and destination IDs. Reference actions and the formal goal stay outside the model input. Generation uses the literal program prefix, greedy decoding and a default limit of 256 new tokens. The next top-level prompt section (another function, object list or task header) ends the target function. Saved programs use a common `def plan():` entry point. The JSON report retains the raw model completion for inspection.

## Run from the repository root

```sh
python main.py progprompt render --task apple_to_counter
python main.py progprompt replay --task cup_to_tray --program tasks/progprompt/cup_to_tray.plan
python main.py progprompt generate --task apple_to_counter --model weights/Llama-3.1-8B-Instruct --save-program runs/apple.plan
python main.py progprompt replay --task apple_to_counter --program runs/apple.plan
```

The included cup program is a human-authored reference for checking symbolic execution. Generation needs the [model environment](../../README.md#requirements) and a local checkpoint. Choose `--device cpu` for CPU execution.

For a smaller checkpoint with a locally verified generation run, download the following public model revision and run the apple task:

```sh
hf download Qwen/Qwen2.5-Coder-0.5B --revision 8123ea2e9354afb7ffcc6c8641d1b2f5ecf18301 --local-dir weights/progprompt-code --include config.json generation_config.json tokenizer.json tokenizer_config.json model.safetensors
python main.py progprompt generate --task apple_to_counter --model weights/progprompt-code --save-program runs/apple.plan
```

With this checkpoint and greedy decoding, the apple program picked up the apple, placed it on the counter and passed the goal checks. For the cup task, the model selected the table as the placement destination and the interpreter rejected the program. The hand-authored cup reference passed. These two runs exercise the local interface and do not measure the paper's benchmark success rate. [Checkpoint revision](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B/tree/8123ea2e9354afb7ffcc6c8641d1b2f5ecf18301)

## Interpret a report

The interpreter validates the syntax of the whole program, including conditional branches. It then reads predicates against the current symbolic scene and applies actions through the tabletop verifier. An `if not holding(...)` guard can acquire an item when the hand is empty. A subsequent `assert holding(...)` checks the updated state. Program text is parsed as a small action language.

The JSON report contains the generated or saved program, the actions attempted, the assertions evaluated, the final state and the goal result. Exit code 0 denotes a satisfied goal, 1 a failed rule, assertion or goal, and 2 an invalid program or input. Failed checks report the restored initial state. Model output that fails to parse is available in the report and in the file requested with `--save-program`.
