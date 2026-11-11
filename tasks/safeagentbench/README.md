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

These records use SafeAgentBench's scene and step schema. Running them requires its simulator environment, scene loading, action mapping and evaluator. The repository's `main.py verify` command accepts the two local tabletop scene schemas described in the root README. A `FloorPlan` name supplies a scene reference, not the initial symbolic state expected by that command.

## Rebuild the same collection

```sh
python scripts/import_safeagentbench.py
```

The importer retrieves a fixed source revision, checks its SHA256 and regenerates `tasks.jsonl` and `selection.json`. It uses the Python standard library. For a previously downloaded source file, pass `--source-file PATH`.

## Attribution

Sheng Yin and the SafeAgentBench contributors, *SafeAgentBench: A Benchmark for Safe Task Planning of Embodied LLM Agents*. Data is redistributed under CC BY 4.0. Changes comprise subset selection, omission of the paired column and addition of local IDs and source row numbers. [Dataset and license declaration](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/52c8da9b57edbd2f5a7c39e9ab22f28f6d6b58df/README.md), [source records](https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/52c8da9b57edbd2f5a7c39e9ab22f28f6d6b58df/safe_detailed.jsonl), [paper](https://arxiv.org/abs/2412.13178), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
