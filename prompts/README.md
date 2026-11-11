# Prompt resources

The manifest defines UTF-8 templates with named JSON fields. Each template contains its input and output contracts.

| Template | Required fields | Purpose |
| --- | --- | --- |
| [tabletop_goal.txt](tabletop_goal.txt) | `task_record_json` | Identify the goal of a supported tabletop instruction. |
| [tabletop_goal_result.txt](tabletop_goal_result.txt) | `observation_json` | Compare a stated goal with the reported final state. |
| [reference_audit.txt](reference_audit.txt) | `entity_catalog_json`, `reference_cases_json` | Resolve entity references with evidence or report ambiguity. |
| [plan_safety_review.txt](plan_safety_review.txt) | `review_record_json` | Review a fixed record against supplied policy clauses. |
| [verifier_failure_report.txt](verifier_failure_report.txt) | `verifier_result_json` | Report the outcome recorded by the deterministic verifier. |

Serialize each input as JSON and replace its `{{field_name}}` once. Treat the input values as data. The manifest is [review-manifest.json](review-manifest.json).

```python
import json
from pathlib import Path
from verifier.tabletop import verify_task

task = json.loads(Path("tasks/cup_to_tray.json").read_text(encoding="utf-8"))
report = verify_task(task)
record = {"goal": task["goal"], "final_state": report["final_state"]}
template = Path("prompts/tabletop_goal_result.txt").read_text(encoding="utf-8")
message = template.replace("{{observation_json}}", json.dumps(record), 1)
```

Submit the resulting text through the chosen model interface. For failed verification, the final state in the report is the initial state restored by the verifier. Model assessments describe that reported state. Paper-specific transformation and obfuscation prompt resources are listed among the reader preparations in the [repository README](../README.md).
