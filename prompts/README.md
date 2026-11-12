# Prompt resources

The [paper prompt inventory](paper/README.md) identifies the five core roles by section and page, alongside the verifier, target planner and external evaluation interfaces. Each role has a separate source record. The templates below are independently authored public resources.

For local task planning, use the [ProgPrompt templates and runner](progprompt/README.md). The resources below take structured records for review.

| Template | Required fields | Purpose |
| --- | --- | --- |
| [request_policy_review.txt](request_policy_review.txt) | `request_record_json` | Classify an incoming tabletop request against supplied policy clauses for human review. |
| [tabletop_chain_fusion.txt](tabletop_chain_fusion.txt) | `merge_record_json` | Reconcile two overlapping action logs for a single cup or apple transfer. |
| [plan_safety_review.txt](plan_safety_review.txt) | `review_record_json` | Review a fixed record against supplied policy clauses. |
| [verifier_failure_report.txt](verifier_failure_report.txt) | `verifier_result_json` | Report the outcome recorded by the deterministic verifier. |

Each UTF-8 template accepts a named JSON field. For example, the following renders the verifier reporting prompt from the result of a tabletop check. [Template manifest](review-manifest.json)

```python
import json
from pathlib import Path
from verifier.tabletop import verify_task

task = json.loads(Path("tasks/cup_to_tray.json").read_text(encoding="utf-8"))
report = verify_task(task)
template = Path("prompts/verifier_failure_report.txt").read_text(encoding="utf-8")
print(template.replace("{{verifier_result_json}}", json.dumps(report), 1))
```

## Tabletop chain fusion

The paper describes Chain Fusion in §5.3.2 (printed page 1063) as part of its intent obfuscation module. This independently written template addresses a narrower problem: combining two partial logs of the same ordinary tabletop transfer. [Paper](https://doi.org/10.1145/3774906.3802758)

Run these commands from the repository root:

```sh
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --render
python main.py progprompt fuse --task cup_to_tray --fragments tasks/progprompt/cup_fragments.json --model weights/Llama-3.1-8B-Instruct
```

In the bundled cup case, one fragment records `grasp → release` and the other records `look → grasp`. The two occurrences of `grasp` refer to the same pickup. The merged order is `look → grasp → release`. Different IDs remain separate events, including repeated inspections. The runner checks event coverage and both source orders, then replays the original actions against the initial scene and terminal goal. A model-reported conflict is an abstention; a verifier failure identifies a rule that the proposed order violates.
