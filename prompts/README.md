# Prompt resources

For local task planning, use the [ProgPrompt templates and runner](progprompt/README.md). The resources below take structured records for review.

The manifest defines UTF-8 templates with named JSON fields. Each template contains its input and output contracts.

| Template | Required fields | Purpose |
| --- | --- | --- |
| [tabletop_chain_fusion.txt](tabletop_chain_fusion.txt) | `merge_record_json` | Reconcile two overlapping action logs for a single cup or apple transfer. |
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

Submit the rendered prompt to the model. When verification fails, the verifier restores the initial symbolic state. Interpret the model's assessment against the state recorded in the report.

## Tabletop chain fusion

The paper describes Chain Fusion in §5.3.2 (printed page 1063) as part of its intent obfuscation module. This independently written template addresses a narrower problem: combining two partial logs of the same ordinary tabletop transfer. [Paper](https://doi.org/10.1145/3774906.3802758)

Run these commands from the repository root:

```sh
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --render
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --model weights/Llama-3.1-8B-Instruct
```

In the bundled cup case, one fragment records `grasp → release` and the other records `look → grasp`. The two occurrences of `grasp` refer to the same pickup. The merged order is `look → grasp → release`. Different IDs remain separate events, including repeated inspections. The runner checks event coverage and both source orders, then replays the original actions against the initial scene and terminal goal. A model-reported conflict is an abstention; a verifier failure identifies a rule that the proposed order violates.
