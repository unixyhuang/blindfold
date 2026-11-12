# ProgPrompt resources

The local planner combines an action interface, available objects, demonstration programs, and a task description. Ordinary task planning uses this shared planner. Prompt resources and source records are collected in this directory; the Python implementation is in [`../../progprompt/`](../../progprompt/). [ProgPrompt project](https://progprompt.github.io/) · [Blindfold paper](https://doi.org/10.1145/3774906.3802758)

## Templates

| File | Role | Entry point |
| --- | --- | --- |
| [header.txt](header.txt) | Tabletop action signatures, state predicates, and program syntax | `progprompt render`, `generate` |
| [demonstrations.txt](demonstrations.txt) | Three task functions with comments, actions, assertions, and recovery branches | `progprompt render`, `generate` |
| [query.txt](query.txt) | Current tabletop objects, initial state, instruction, and function header | `progprompt render`, `generate` |
| [task_planning.txt](task_planning.txt) | Ordinary SafeAgentBench program generation from a task and room inventory | `progprompt benchmark` |
| [dominant_action_identification.txt](dominant_action_identification.txt) | Empty prompt slot for the paper's §5.3.1 role | Unfilled placeholder |
| [verifier_feedback.txt](verifier_feedback.txt) | Read-only reporting of an existing verifier result | `progprompt feedback` |
| [chain_fusion.txt](chain_fusion.txt) | Reconciliation of two partial logs of the same tabletop transfer | `progprompt fuse` |

For tabletop generation, the renderer takes the instruction and initial scene. The scene schema supplies the valid action arguments. The verifier receives the terminal goal and checks the generated actions independently. Generated programs are interpreted using the declared action language.

## Planning

Run from the repository root:

```sh
python main.py progprompt render --task apple_to_counter
python main.py progprompt generate --task apple_to_counter --model weights/Llama-3.1-8B-Instruct --save-program runs/apple.plan
python main.py progprompt replay --task apple_to_counter --program runs/apple.plan
```

The model generates a continuation of the task function. The runner preserves the raw completion and saves a common `def plan():` entry point for replay. `cup_to_tray` and `apple_to_counter` have complete symbolic initial states. [Model environment](../../README.md#requirements)

The task planning template uses a room's object-type list and the task instruction to produce a SafeAgentBench program. The batch runner checks the generated steps against the reviewed goal. The [100-task guide](safeagentbench.md) documents the NF4 checkpoint, inventory provenance, run parameters, and output reports.

## Verifier feedback

The feedback command accepts a single tabletop verification, benchmark task result, generated-program result, or merge report. Save a verifier record as JSON and supply it to the command:

```sh
python main.py verify --task tasks/cup_to_tray.json > cup-verifier.json
python main.py progprompt feedback --record cup-verifier.json
python main.py progprompt feedback --record cup-verifier.json --render
python main.py progprompt feedback --record cup-verifier.json --model weights/Llama-3.1-8B-Instruct
```

The adapter collects the status and diagnostic fields present in the record, preserving their order, indices, null values, and messages. The default command produces that envelope deterministically. An unknown result retains its unknown status. With `--model`, the model reports the envelope for inspection, and the command compares its reply with the deterministic expected envelope before accepting it. A modified field or invalid JSON produces `feedback_mismatch`. Changing the action plan or verifier verdict is outside this reporting interface.

## Chain fusion

Each input fragment is an ordered list of events from one supported tabletop transfer. A shared ID identifies one shared event; distinct IDs retain distinct events even when their action text matches. The prompt receives one event table plus precedence constraints derived from both fragments.

```sh
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --render
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --model weights/Llama-3.1-8B-Instruct
```

The runner checks complete event coverage and each fragment's order, then replays the original event actions through the tabletop verifier. The bundled cup fragments require `look → grasp → release`. A conflict reply records model abstention. A rejected candidate retains the rule that failed.

## Relationship to the paper

| Resource | Paper source | Artifact scope |
| --- | --- | --- |
| Shared planner | §4.1, §5.2.1, §6.1 | Local ProgPrompt-style planning for the released ordinary tasks |
| Task planning | External planning context in §4.1 and §6.1 | SafeAgentBench task programs using the local action vocabulary |
| Dominant action identification | §5.3.1, printed page 1062, PDF page 6 | Empty prompt file with a separate source record |
| Verifier feedback | §5.4.1, printed page 1064 | Validated reporting of existing symbolic findings |
| Chain fusion | §5.3.2, printed page 1063 | Two partial records of the same cup or apple transfer |

The dominant-action identification slot is registered under `placeholders` in [manifest.json](manifest.json) and has an empty body. Runtime templates are listed under `templates`. The following source records retain their paper locations:

- [Command sanitization](command_sanitization.md), §5.2.2, printed page 1061.
- [Dominant action identification](dominant_action_identification.md), §5.3.1, printed page 1062.
- [Cover branch creation and completion](cover_branch_generation.md), §5.3.2, printed page 1063.

Run `python main.py progprompt check-prompts` to inspect template files, field contracts, and implemented entry points. It performs no model calls and exits with code 1 while the full paper workflow is incomplete. Filling the dominant-action text alone does not add its runtime handler or the other missing paper components.

The paper prints simplified material for several roles. The public executable templates in this directory are independently authored adaptations, with behavior defined by their input contracts and the associated symbolic checks.
