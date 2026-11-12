# ProgPrompt resources

The local planner combines an action interface, available objects, demonstration programs, and a task description. Ordinary task planning uses this shared planner. All prompt bodies in this directory use UTF-8 `.txt` files. Markdown files document the interfaces and paper locations; [manifest.json](manifest.json) records file roles and rendering contracts. The Python implementation is in [`../../progprompt/`](../../progprompt/). [ProgPrompt project](https://progprompt.github.io/) · [Blindfold paper](https://doi.org/10.1145/3774906.3802758)

## Executable templates

| File | Role | Entry point |
| --- | --- | --- |
| [header.txt](header.txt) | Tabletop action signatures, state predicates, and program syntax | `progprompt render`, `generate` |
| [demonstrations.txt](demonstrations.txt) | Three task functions with comments, actions, assertions, and recovery branches | `progprompt render`, `generate` |
| [query.txt](query.txt) | Current tabletop objects, initial state, instruction, and function header | `progprompt render`, `generate` |
| [task_planning.txt](task_planning.txt) | Ordinary SafeAgentBench program generation from a task and room inventory | `progprompt benchmark` |
| [verifier_feedback.txt](verifier_feedback.txt) | Read-only reporting of an existing verifier result | `progprompt feedback` |
| [tabletop_chain_fusion.txt](tabletop_chain_fusion.txt) | Reconciliation of two partial logs of the same tabletop transfer | `progprompt fuse` |

The separate paper-role texts listed below are supplied source material. They are not loaded by these commands. In particular, `chain_fusion.txt` describes the paper role, while `tabletop_chain_fusion.txt` implements the fixed-event ordering interface accepted by the tabletop verifier.

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

## Tabletop fragment reconciliation

Each input fragment is an ordered list of events from one supported tabletop transfer. A shared ID identifies one shared event; distinct IDs retain distinct events even when their action text matches. The prompt receives one event table plus precedence constraints derived from both fragments.

```sh
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --render
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --model weights/Llama-3.1-8B-Instruct
```

The runner checks complete event coverage and each fragment's order, then replays the original event actions through the tabletop verifier. The bundled cup fragments require `look → grasp → release`. A conflict reply records model abstention. A rejected candidate retains the rule that failed.

## Paper coverage

| Role | Paper location | Resource and coverage |
| --- | --- | --- |
| Shared planning / proxy planning | §4.1, p. 1059 / PDF 3; §5.2.1, p. 1061 / PDF 5; §6.1, p. 1064 / PDF 8 | `header.txt`, `demonstrations.txt`, `query.txt`, and `task_planning.txt` provide ordinary ProgPrompt-style planning. The paper's proxy-planning example is simplified; these executable templates are adaptations. |
| Command sanitization | §5.2.2, p. 1061 / PDF 5 | [command_sanitization.txt](command_sanitization.txt): supplied text, no runtime handler. The paper describes the role and gives before/after examples, without a separate prompt box. |
| Dominant action identification | §5.3.1, p. 1062 / PDF 6 | [dominant_action_identification.txt](dominant_action_identification.txt): supplied text, no runtime handler. The paper gives one simplified scoring/identification example. |
| Cover branch creation and completion | §5.3.2, p. 1063 / PDF 7 | [cover_branch_generation.txt](cover_branch_generation.txt): supplied text, no runtime handler. The paper uses one simplified prompt for both stages. |
| Chain fusion | §5.3.2, p. 1063 / PDF 7 | [chain_fusion.txt](chain_fusion.txt): supplied text, no runtime handler. The paper gives a separate simplified example. The executable tabletop adapter is a different contract. |
| Verifier feedback | §5.4.1, p. 1064 / PDF 8 | [verifier_feedback.txt](verifier_feedback.txt): read-only reporting adaptation. The paper describes structured feedback and iterative revision, without publishing an independent feedback prompt; the revision loop is not implemented. |

The paper contains four simplified prompt boxes: proxy planning, dominant-action identification, cover branch generation, and chain fusion. They do not constitute complete runtime templates. The role index above covers the prompting stages described in the paper; file presence does not establish a complete reproduction. Branch creation and completion share one resource, and ordinary planning reuses the shared planner rather than separate target/proxy prompt files.

The four supplied paper-role texts are registered under `paper_prompts` in [manifest.json](manifest.json). Their `provided` status means that the body exists; it does not assert exact transcription, completeness, or executable integration. Runtime templates are separately listed under `templates` and define the current command interfaces. The supplied texts are preserved without adding missing examples or task data.

Run `python main.py progprompt check-prompts` to inspect file coverage, runtime template fields, and implemented entry points. It performs no model calls and exits with code 1 while the full paper workflow is incomplete. Nonempty paper-role text does not supply the corresponding runtime handler, the planner-verifier revision loop, or simulator integration.
