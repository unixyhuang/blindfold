# SafeAgentBench · 100 household tasks

This collection contains 100 records selected from the official `safe_detailed` split. It covers 75 distinct scenes, with 9 short tasks (2–3 steps), 68 medium tasks (4–5 steps) and 23 long tasks (6–10 steps).

The source contains 300 records. Selection first covers the eligible scenes, then fills the step-count strata using a fixed hash ordering and unique case-folded instructions. The collection focuses on household manipulation without heating, slicing, dropping or throwing. The exact source filters, revision, checksums, source row numbers and counts are recorded in [selection.json](selection.json). This subset was selected for this repository. The upstream benchmark does not define it as an official evaluation split.

## Records

[tasks.jsonl](tasks.jsonl) has one JSON object per line.

| Field | Meaning |
| --- | --- |
| `task_id` | Local stable ID based on the source row number. |
| `source_row` | One-based line number in the pinned upstream file. |
| `instruction` | Original ordinary-task instruction. |
| `scene_name` | Original simulator scene name, such as `FloorPlan203`. |
| `step` | Original recorded steps. |
| `final_state` | Original final-state annotation, which can be `null`. |

The paired `risk_instruction` column is omitted. Original text and annotations in the four retained source fields are preserved. Of the 100 records, 65 have `final_state: null`. The source may contain other inconsistencies. For example, source row 24 has steps and a toggle-state annotation that should be reviewed before scoring. No missing annotations were inferred.

## Read the collection

Run from the repository root:

```python
import json
from pathlib import Path

path = Path("tasks/safeagentbench/tasks.jsonl")
tasks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
assert len(tasks) == 100
print(tasks[0]["task_id"], tasks[0]["instruction"])
```

## Verify the records

```sh
python main.py verify --benchmark safeagentbench
python main.py verify --benchmark safeagentbench --scene FloorPlan203
python main.py verify --benchmark safeagentbench --task-id sab-safe-0085
python main.py verify --task /path/to/single-record.json
```

Batch and scene reports include a summary and the selected records in source order. A task ID or single JSON file returns one report. The verifier starts each trace with an empty hand and represents each named object type as one logical object in that trace. Each object must first be introduced by `find`. Placement needs a held item and rejects containment cycles or placement into an explicitly closed box, cabinet, drawer or fridge. The checker follows recorded placements through nested containers. Object names ignore case and spaces. Room geometry, instance identity, affordances and reachability require simulator observations.

The supported step vocabulary is `find`, `pick`, `put`, `open`, `close`, `turn on`, `turn off`, `clean`, `fillLiquid` and `pour` with the object and liquid names used in this collection. Explicit successful actions establish facts such as an open door or filled mug. A pour rotates the held object. The source and destination liquid outcomes require observations. [Upstream controller](https://github.com/shengyin1224/SafeAgentBench/blob/38ca3ab27eb8a5f5034a50bdcc5cbab23ce8f089/low_level_controller/low_level_controller.py#L584)

`trace_status` reports whether the sequence is internally consistent. `goal_status` is `supported`, `contradicted` or `unknown` under the assumption that the recorded actions succeed. The `checks` array reports each predicate and its evidence step, indexed from zero. A missing annotation or an unobserved property can leave the goal unknown even when the steps are consistent. Exit code 0 means the check completed without finding a contradiction, 1 means at least one contradiction, and 2 means invalid input.

All 100 bundled traces are internally consistent. Among the 35 annotated goals, 29 have support, one contradicts a recorded effect and five need additional evidence. For instance, `sab-safe-0071` places a mug on a dining table while the annotation names a countertop. The report records the differing destination and leaves the full parent chain unknown. The other 65 records have no goal annotation.

### Check observed final state

Save the full, unfiltered `controller.last_event.metadata` as JSON at the end of the selected task's run. Supply it with that task:

```sh
python main.py verify --benchmark safeagentbench --task-id sab-safe-0085 --metadata final-event.json
```

The snapshot must include the matching `sceneName` and the full `objects` array with unique `objectId` values and `objectType` names. Use the snapshot from the correct run because several tasks can share a scene. The independent `observed_goal` result checks each annotation against actual instances. All predicates for an annotated object must hold on the same instance. Container relations resolve object IDs and compare types. Missing fields and unresolved relation IDs can leave a predicate unknown. A final snapshot supplies evidence about the goal state. Establishing which actions occurred requires an execution log. [Upstream goal evaluator](https://github.com/shengyin1224/SafeAgentBench/blob/38ca3ab27eb8a5f5034a50bdcc5cbab23ce8f089/evaluator/detail_evaluate.py#L52)

## Rebuild the same collection

```sh
python scripts/import_safeagentbench.py
```

The importer retrieves a fixed source revision, checks its SHA256 and regenerates `tasks.jsonl` and `selection.json`. It uses the Python standard library. For a previously downloaded source file, pass `--source-file PATH`.

## Attribution

Sheng Yin and the SafeAgentBench contributors, *SafeAgentBench: A Benchmark for Safe Task Planning of Embodied LLM Agents*. Data is redistributed under CC BY 4.0. Changes comprise subset selection, omission of the paired column and addition of local IDs and source row numbers. [Dataset and license declaration](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/52c8da9b57edbd2f5a7c39e9ab22f28f6d6b58df/README.md), [source records](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/52c8da9b57edbd2f5a7c39e9ab22f28f6d6b58df/safe_detailed.jsonl), [paper](https://arxiv.org/abs/2412.13178), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
