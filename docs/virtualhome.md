# VirtualHome interface

For a self-contained three-task optimization and verifier-feedback workflow, use the bundled Evolving Graph backend described in the [ordinary workflow guide](ordinary-workflow.md). This page covers the separate native Unity backend. `virtualhome run --optimize --max-repairs 2` applies the ordinary workflow before Unity execution; `virtualhome inspect` reads the Unity service.

The `virtualhome` command connects ordinary tabletop transfer plans to VirtualHome's Unity simulator. It supports the bundled `cup_to_counter`, `apple_to_counter`, and `cup_to_tray` tasks, using actual scene object IDs. The Python client uses the standard library and follows the [official Unity HTTP protocol](https://github.com/xavierpuigf/virtualhome/blob/58970fd80951c2eaa1af713e0917d1a105353ad8/virtualhome/simulation/unity_simulator/comm_unity.py). It does not require installing the upstream `virtualhome` Python package into the model environment.

## Prepare the simulator

Obtain a VirtualHome Unity executable separately. The [official repository](https://github.com/xavierpuigf/virtualhome#download-unity-simulator) lists platform downloads. An official Windows build is also available in the [v2.0.0 release](https://github.com/xavierpuigf/virtualhome/releases/tag/v2.0.0). Keep the executable and its accompanying data directory together, outside the source checkout. The Python client alone does not install or emulate Unity.

Start one instance with its HTTP port set to 8080. Substitute the executable filename from the downloaded build; the official v2.0 Windows archive names it `2013_10 - Sample Assets.exe`. In Windows PowerShell:

```powershell
Start-Process -FilePath "C:\path\to\2013_10 - Sample Assets.exe" -ArgumentList "-http-port=8080", "-batchmode", "-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "480" -WindowStyle Hidden
```

Use Python 3.11 to inspect the connection and export the graph. `--environment 0` explicitly resets the scene; omitting that argument reads the current scene without resetting it.

```sh
python main.py virtualhome inspect --environment 0 --output runs/virtualhome-scene.json
```

The saved JSON contains `nodes` with integer `id` and `class_name` values, and `edges` with `from_id`, `to_id`, and `relation_type`. Scene availability and object inventories depend on the executable. A failed connection returns `unavailable` with exit code 2.

The client first uses the newer `clear` / `environment` reset protocol. Only an explicit `Unknown action clear` response selects the [v2.0 `reset` protocol](https://github.com/xavierpuigf/virtualhome/blob/v2.0.0/simulation/unity_simulator/comm_unity.py#L139-L145). Other failures and lost acknowledgements do not trigger a fallback or retry. Run reports record the selected reset protocol.

## Bind objects

The adapter maps symbolic task IDs to Unity graph IDs. Automatic binding requires a unique matching item and destination. It uses the item's unique initial `ON` edge as `table_1`. Ambiguous objects require an explicit JSON file passed through `--bindings`.

For `cup_to_counter`, the keys are `cup_1`, `counter_1`, and optionally `table_1`. For `apple_to_counter`, use `apple_1`, `counter_1`, and optionally `table_1`. For `cup_to_tray`, use `cup_1`, `tray_1`, and optionally `table_1`. Values must be integer IDs from the selected graph. For instance, a binding object has the form `{"cup_1": 17, "counter_1": 52, "table_1": 8}`; replace those numbers with observed IDs before using it.

The tested official v2.0 Windows build, scene 0, uses the following `runs/cup-bindings.json` for `cup_to_counter`. Check the exported graph when using another build or scene:

```json
{"cup_1": 197, "counter_1": 239, "table_1": 111}
```

Accepted item classes are `apple`, `cup`, and `mug`. A counter destination must be `kitchencounter`; a tray must be `tray`. Missing classes and ambiguous instances stop the run. The adapter does not substitute a plate for a missing tray. The item must start on one observed support separate from its destination, unheld. For `cup_to_tray`, the tray must share that initial support. `run` resets the selected scene and adds one character before binding, so prepare IDs for the same scene and executable.

## Execute a transfer

First check the interface with the task's recorded reference actions. This mode does not call a model:

```sh
python main.py virtualhome run --task cup_to_counter --recorded --environment 0 --bindings runs/cup-bindings.json --output-dir runs/virtualhome-reference
```

Alternatively, check and execute a saved ProgPrompt program:

```sh
python main.py progprompt generate --task cup_to_counter --model weights/llama31-8b-instruct-nf4 --save-program runs/cup.plan
python main.py virtualhome run --task cup_to_counter --program runs/cup.plan --environment 0 --bindings runs/cup-bindings.json --output-dir runs/virtualhome-program
```

The combined model entry point performs generation, symbolic checking, graph binding, execution, and observed-goal checking:

```sh
python main.py virtualhome run --task cup_to_counter --model weights/llama31-8b-instruct-nf4 --environment 0 --bindings runs/cup-bindings.json --output-dir runs/virtualhome-model
```

Model mode uses the [shared model dependencies](../README.md#requirements) and the planner's default chat-formatted complete-function interface. `--input-format completion` selects raw causal continuation. An invalid or failing generated program is reported as `invalid_plan` before the simulator is reset or any actions are sent. Each run requires an empty output directory. Omit `--bindings` only when automatic binding is unambiguous. `--host`, `--port`, and `--timeout` configure the Unity connection.

## Action and verification contract

| Symbolic action | Unity script |
| --- | --- |
| `inspect(item)` | `walk`, `turnto`, `lookat` |
| `pick(item)` | `walk`, `grab` |
| `place(item, destination)` | `walk` to the destination, then `putback` |

These mappings use Unity's [documented action interface](https://github.com/xavierpuigf/virtualhome/blob/58970fd80951c2eaa1af713e0917d1a105353ad8/virtualhome/simulation/README.md#supported-in-unity-simulator). Scripts retain the graph's object class names and IDs. `find_solution=False` preserves those instance bindings. Recording is disabled and animation is skipped. Execution stops at the first rejected script line, retaining the Unity message and the originating symbolic action index. Mutating requests are never retried: a lost acknowledgement can leave the scene partially changed.

After execution the adapter reads a new graph. Success requires both an `ON` relation from the bound item to the bound destination and no `HOLDS_LH` or `HOLDS_RH` relations from the character. A successful HTTP or Unity response alone is insufficient. Missing observations and unacknowledged execution remain `unknown`. Explicitly rejected execution remains `execution_failed`, even when the final graph cannot be read.

The symbolic preflight uses the bundled task abstraction. Unity graph checks establish placement and empty hands; they do not establish liquid content, temperature, or every symbolic initial-state assumption. Unity's own action checks determine whether physical interaction succeeds.

The output directory contains `report.json`, available `before_graph.json` and `after_graph.json`, resolved `bindings.json`, `script.txt`, and a generated or supplied `plan.py` when applicable. `report.json` separates the symbolic planner verdict, individual execution acknowledgements, and observed goal checks. Exit codes are 0 for `passed`, 1 for failed or unknown execution/outcomes, and 2 for invalid plans, input errors, or unavailable services.

## Scope

The 100 SafeAgentBench tasks use AI2-THOR scene identifiers and actions. They are not VirtualHome scenes and cannot be executed by translating `FloorPlan` numbers into Unity scene indices. This adapter covers the three bundled transfer tasks. Additional VirtualHome tasks require appropriate native scenes, instance bindings, action mappings, and observed goal definitions.

The supplied paper-role prompts are not invoked by this interface. The full paper workflow remains incomplete; `python main.py progprompt check-prompts` reports its missing components. A real Unity executable is needed to validate engine execution. The automated localhost protocol fixtures verify client and adapter behavior without constituting a Unity simulation.

## Engine validation

The official v2.0 Windows archive has SHA-256 `2f0e432fb7081575c95fa46254d085fcd9170f5abff55047f33aebc649e86f52`. In scene 0, both the recorded `cup_to_counter` run and the combined Llama-3.1-8B-Instruct NF4 model run completed through `main.py`. All four native script lines were acknowledged, and the returned graph established `mug(197) ON kitchencounter(239)` with empty character hands.

The optimized workflow was also checked on the same native scene with an action-only program that attempted placement before acquisition. Verifier feedback triggered one repair; the four native script lines then completed, with the same independently observed placement and empty-hand outcome.

The same build rejected tested apple interactions with `Script is impossible to execute` or `No interaction positions`; these are retained as execution failures. The inspected scenes did not contain a `tray`, so the cup-to-tray task could not be bound there. The v2.3 protocol is covered by local protocol fixtures, without a real v2.3 binary validation. The checked v2.3 download links from the upstream README were unavailable during validation.
