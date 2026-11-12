# Ordinary transfer optimization and feedback repair

This workflow supports exactly three released tasks: `cup_to_tray`, `apple_to_counter`, and `cup_to_counter`. It preserves each task's initial scene, object IDs, and terminal goal. Planning can use local Llama-3.1 weights, a saved task program, an explicit action array, or recorded reference actions.

## Run all three tasks

VirtualHome's Evolving Graph engine is included as a small, unmodified upstream dependency with its MIT license. Python 3.11 and the standard library are sufficient for the recorded/action-input workflow. No Unity executable, network service, model weights, or upstream Python-package installation is required for this backend.

From the repository root:

```sh
python main.py virtualhome run --backend evolving-graph --task cup_to_tray --recorded --optimize --max-repairs 2 --output-dir runs/ordinary-cup-tray
python main.py virtualhome run --backend evolving-graph --task apple_to_counter --recorded --optimize --max-repairs 2 --output-dir runs/ordinary-apple-counter
python main.py virtualhome run --backend evolving-graph --task cup_to_counter --recorded --optimize --max-repairs 2 --output-dir runs/ordinary-cup-counter
```

Each output directory must be empty. Recorded mode uses the task's reference actions and is labeled `recorded_reference`. It does not demonstrate model generation. To generate a new plan with local Hugging Face weights, install the [model dependencies](../README.md#requirements) and use:

```sh
python main.py virtualhome run --backend evolving-graph --task cup_to_tray --model weights/llama31-8b-instruct-nf4 --optimize --max-repairs 2 --output-dir runs/ordinary-model-cup-tray
```

`--program PATH` supplies a saved `def plan():` function. `--actions PATH` supplies a JSON array of `inspect`, `pick`, and `place` records. All arguments must refer to the selected task's fixed item and destination.

## Optimization and repair

| Stage | Behavior and evidence |
| --- | --- |
| Source verification | Recheck the program or complete action array, preserving the original source and diagnostics. A supplied `passed` label is not trusted. |
| Feedback repair | On eligible failures, use the exact fresh verifier report to search for a legal ordering and minimally insert a missing `pick` or `place`. Preserve every supplied action record during repair. |
| Equivalent optimization | For a successful trace, remove `inspect` actions that have no effect on the defined symbolic state. Existing state-changing actions cannot be deleted or added. Both full symbolic final states must match. |
| Final verification | Build and check the selected program again, including placement and empty-hand assertions. Only a passing candidate reaches the simulator. |
| VirtualHome verification | Execute native action lines in the selected backend. Read the resulting graph and independently check the bound placement relation and empty character hands. |

Search is bounded to 64 actions and at most one inserted `pick` and one inserted `place`. It does not read the task's recorded reference actions as a repair answer. `--max-repairs` accepts 0 through 3 and defaults to 2. A repeated candidate, an unrepaired trace, an invalid candidate, or the attempt limit ends the workflow.

Failed programs with assertions or control flow are not automatically reduced to their executed prefix. Failed assertions and invalid syntax remain failures. Automatic program repair accepts only fully parsed, linear action-only functions, using their complete action sequence including an unexecuted suffix. This prevents a later assertion or action from disappearing when an earlier action fails. Successful programs retain their original verification record; optimization operates on their verified execution path.

For a concrete feedback-repair input, save this array as `runs/incomplete-cup.json`:

```json
[{"action": "place", "object": "cup_1", "target": "counter_1"}]
```

Then run:

```sh
python main.py virtualhome run --backend evolving-graph --task cup_to_counter --actions runs/incomplete-cup.json --optimize --max-repairs 1 --output-dir runs/repaired-cup-counter
```

The original trace fails because the cup is not held. The feedback record identifies that failed precondition. Repair inserts a legal acquisition before placement; the candidate is checked again and then executed in the graph engine. To inspect optimization without invoking a simulator:

```sh
python main.py progprompt optimize --task cup_to_counter --actions runs/incomplete-cup.json --max-repairs 1 --output-dir runs/optimization-only
```

Repair consumes structured verifier diagnostics directly. The separate `progprompt feedback` command remains a read-only reporting interface. This workflow does not invoke the paper-role prompt files.

## Backend and output contracts

`--backend evolving-graph` uses the official VirtualHome `EnvironmentState` and `ScriptExecutor` on a kitchen graph projected from the selected task. Environment 0 identifies this authored graph, rather than Unity scene 0. The graph uses one character, one support, the item and its destination; object bindings are unambiguous. The vendored code, revision, source hashes and license are documented in [the dependency notice](../third_party/virtualhome_evolving_graph/NOTICE.md).

This backend verifies symbolic action/state transitions. It does not validate Unity assets, rendering, collision geometry, inverse kinematics or navigation. The upstream graph executor also omits some physical-placement constraints; the released verifier separately checks the task's declared initial conditions and destination availability. Empty-cup, ambient-temperature and whole-apple assumptions originate in the task data.

For native Unity execution, select `--backend unity` and prepare its executable and instance bindings using the [Unity guide](virtualhome.md). The same `--optimize --max-repairs 2` flags connect the ordinary workflow to Unity. Actual Unity failures or uncertain acknowledgements remain execution failures or unknown outcomes; they are not blindly retried or converted into successful symbolic verdicts.

Every run writes `report.json`. Optimized runs also write `workflow.json`, with the source verifier result, repair inputs, exact feedback, all candidates, fresh candidate verdicts, transformation indices, equivalence result and termination reason. `original-plan.py` preserves a supplied/generated program, while `plan.py` contains the selected checked program. `before_graph.json`, `after_graph.json`, `bindings.json` and `script.txt` provide backend evidence when available. The report's `backend` and upstream revision distinguish graph simulation from Unity.

Only the three ordinary task contracts are supported by this workflow. The paper's action-chain prompts run through the separate [`progprompt attack`](attack-workflow.md) pipeline; the full paper pipeline remains partial because target-model querying and paper-specific simulator execution are unimplemented.
