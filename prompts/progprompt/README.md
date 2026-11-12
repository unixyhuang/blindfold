# ProgPrompt resources

The local planner combines an action interface, available objects, demonstration programs, and a task description. Ordinary task planning uses this shared planner. All prompt bodies in this directory use UTF-8 `.txt` files. Markdown files document the interfaces and paper locations; [manifest.json](manifest.json) records file roles and rendering contracts. The Python implementation is in [`../../progprompt/`](../../progprompt/). [ProgPrompt project](https://progprompt.github.io/) · [Blindfold paper](https://doi.org/10.1145/3774906.3802758)

## Executable templates

| File | Role | Entry point |
| --- | --- | --- |
| [header.txt](header.txt) | Tabletop action signatures, state predicates, and program syntax | `progprompt render`, `generate` |
| [demonstrations.txt](demonstrations.txt) | Three task functions with comments, actions, assertions, and recovery branches | `progprompt render`, `generate` |
| [query.txt](query.txt) | Current tabletop objects, initial state, instruction, and function header | `progprompt render`, `generate` |
| [tabletop_chat.txt](tabletop_chat.txt) | Chat request for a complete task function, with the shared ProgPrompt context | `progprompt render`, `generate` |
| [task_planning.txt](task_planning.txt) | Ordinary SafeAgentBench program generation from a task and room inventory | `progprompt benchmark` |
| [verifier_feedback.txt](verifier_feedback.txt) | Read-only reporting of an existing verifier result | `progprompt feedback` |
| [tabletop_chain_fusion.txt](tabletop_chain_fusion.txt) | Reconciliation of two partial logs of the same tabletop transfer | `progprompt fuse` |
| [chain_command_transformer.txt](chain_command_transformer.txt) | Attack action chain from a malicious intent, action pool, and scene | `progprompt attack` |
| [chain_sanitization.txt](chain_sanitization.txt) | Runtime wrapper around the supplied command-sanitization paper prompt | `progprompt attack` |
| [chain_dominant_action.txt](chain_dominant_action.txt) | Runtime wrapper around the supplied dominant-action identification prompt | `progprompt attack` |
| [chain_cover_branch.txt](chain_cover_branch.txt) | Runtime wrapper around the supplied cover branch creation/completion prompt | `progprompt attack` |
| [chain_fusion_runtime.txt](chain_fusion_runtime.txt) | Runtime wrapper around the supplied chain fusion prompt | `progprompt attack` |
| [chain_repair.txt](chain_repair.txt) | Planner-verifier repair from structured verifier feedback | `progprompt attack` |

The four supplied paper-role texts remain byte-identical source material. `chain_sanitization.txt`, `chain_dominant_action.txt`, `chain_cover_branch.txt`, and `chain_fusion_runtime.txt` embed them verbatim and add a runtime input field plus a strict JSON output contract. `manifest.json` records each source digest, and `check-prompts` reports a changed body as invalid. The tabletop adapter `tabletop_chain_fusion.txt` keeps its separate fixed-event ordering contract.

For tabletop generation, the renderer takes the instruction and initial scene. The scene schema supplies the valid action arguments. The verifier receives the terminal goal and checks the generated actions independently. Generated programs are interpreted using the declared action language.

## Planning

Run from the repository root:

```sh
python main.py progprompt render --task apple_to_counter
python main.py progprompt generate --task apple_to_counter --model weights/Llama-3.1-8B-Instruct --save-program runs/apple.plan
python main.py progprompt replay --task apple_to_counter --program runs/apple.plan
```

The default model input uses its Hugging Face chat template and requests a complete `def plan():` function. `tabletop_chat.txt` wraps the shared action interface, demonstrations and task context. The runner preserves the raw response and checks the generated function without removing failed assertions. `cup_to_tray`, `cup_to_counter`, and `apple_to_counter` have complete symbolic initial states. To use the original raw causal continuation interface, pass `--input-format completion` to `render` or `generate`. [Model environment](../../README.md#requirements)

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

## Action-chain pipeline

The attack chain stages run in order: proxy planning, sanitization, dominant action identification, cover branch creation and completion, chain fusion, then a bounded planner-verifier repair loop. Each reply is validated as strict JSON before the next stage, and the fused chain is replayed by the symbolic chain verifier.

```sh
python main.py progprompt attack --task phone_into_oven --recorded --output-dir runs/attack-recorded
python main.py progprompt attack --task phone_into_oven --render-stage chain_fusion
```

`--recorded` replays authored reference replies; `--model` runs every stage with local weights; `--responses` replays a JSON object of stage replies. The run writes each populated prompt, each raw reply, `attack.json`, and on success `final-chain.json`. [Stage contracts and symbolic verifier rules](../../docs/attack-workflow.md)

## Paper coverage

| Role | Paper location | Resource and coverage |
| --- | --- | --- |
| Proxy planning / command transformer | §5.2.1, p. 1061 / PDF 5 | `chain_command_transformer.txt` implements the paper's action-pool, scene-state and reasoning-process prompt for the bundled symbolic scene. |
| Command sanitization | §5.2.2, p. 1061 / PDF 5 | [command_sanitization.txt](command_sanitization.txt) is embedded verbatim by `chain_sanitization.txt` and checked for one implicit command per action. |
| Dominant action identification | §5.3.1, p. 1062 / PDF 6 | [dominant_action_identification.txt](dominant_action_identification.txt) is embedded verbatim by `chain_dominant_action.txt`; scores are checked against Eq. 4. |
| Cover branch creation and completion | §5.3.2, p. 1063 / PDF 7 | [cover_branch_generation.txt](cover_branch_generation.txt) is embedded verbatim by `chain_cover_branch.txt`; the branch is executed from the predecessor state. |
| Chain fusion | §5.3.2, p. 1063 / PDF 7 | [chain_fusion.txt](chain_fusion.txt) is embedded verbatim by `chain_fusion_runtime.txt`; both input chains must survive in order. |
| Planner-verifier loop | §5.4.1, p. 1064 / PDF 8 | `chain_repair.txt` consumes the raw verifier report plus the shared normalized feedback envelope; `verifier/attack.py` implements the FSM of Eq. 7-10. |
| Read-only feedback reporting | §5.4.1, p. 1064 / PDF 8 | [verifier_feedback.txt](verifier_feedback.txt) remains a separate reporting adaptation. The ordinary-task workflow consumes structured diagnostics directly. |

The paper contains four simplified prompt boxes: proxy planning, dominant-action identification, cover branch generation, and chain fusion. The runtime wrappers add the missing input fields and JSON output contracts; they do not claim the paper's exact unseen examples. Branch creation and completion share one resource.

The four supplied paper-role texts are registered under `paper_prompts` in [manifest.json](manifest.json). Their `provided` status means that the body exists and matches its recorded digest; the `runtime_handler` and `runtime_template` fields connect each body to `progprompt attack`. Runtime templates are separately listed under `templates` and define the current command interfaces.

Run `python main.py progprompt check-prompts` to inspect file coverage, runtime template fields, and implemented entry points. It performs no model calls and exits with code 1 while the full paper workflow is incomplete. The target embodied-LLM query and paper-specific simulator execution remain unimplemented, and are reported as the remaining components.
