# Prompt inventory

The first two English templates let a model label the goal and observed outcome of the two bundled tabletop tasks. The other three support human review of fixed records. Each template contains its instructions, fields, output contract and worked examples. All five were written for this artifact. The paper gives excerpts and method descriptions.

| Template | Inputs | Output |
| --- | --- | --- |
| [Tabletop goal identification](tabletop_goal.txt) | The bundle's instruction and initial scene | A fixed goal with grounded entity IDs, or a status explaining why a goal could not be matched. |
| [Tabletop final-state assessment](tabletop_goal_result.txt) | The bundle's goal and the verifier's reported final state | Predicate results for placement, occupancy and gripper state, plus an overall outcome. |
| [Entity reference audit](reference_audit.txt) | Entity catalog and marked mentions in existing text | One binding per mention, with an entity ID and a verbatim supporting passage when resolved. Ambiguous mentions receive `unknown`. |
| [Physical consequence review](plan_safety_review.txt) | Fixed event record, scene facts and applicable policy clauses, all with IDs | One finding citing the clauses and observations that support it. Missing facts yield `needs_review`. |
| [Verifier result report](verifier_failure_report.txt) | A recorded verifier result with its index convention and errors | A faithful transcription of the reported outcome and failures. A contradictory record yields `invalid_input`. |

**Rendering.** Serialize each input value as JSON, then substitute the resulting string into its named `{{field_name}}` placeholder once. Template names and required fields are in the [review manifest](review-manifest.json). Text inside an input value is data. Only the template file is parsed for placeholders. Worked outputs illustrate the response contract and have not been evaluated against an instruction-tuned model.

### Use a bundled task

Run this example from the artifact root. It prepares two independent user messages for a local model.

```python
import json
from pathlib import Path
from demo.tabletop import verify_task

bundle = json.loads(Path("assets/examples/task_bundle.json").read_text(encoding="utf-8"))
report = verify_task(bundle)

def fill(filename, field, record):
    template = (Path("prompts") / filename).read_text(encoding="utf-8")
    return template.replace("{{" + field + "}}", json.dumps(record, ensure_ascii=False), 1)

goal_message = fill("tabletop_goal.txt", "task_record_json", {
    "instruction": bundle["instruction"], "scene": bundle["scene"]
})
outcome_message = fill("tabletop_goal_result.txt", "observation_json", {
    "goal": bundle["goal"], "final_state": report["final_state"]
})
```

To try either template with `llama3.1`, use the resulting string as the user message's `content` in the [local Ollama example](../examples/ollama_local.py). For the supplied cup record, the reference goal is `{"on":["cup_1","tray_1"],"held":null}` and the reference outcome is `met`. A failed verifier run reports its rolled-back state. The assessment then describes that snapshot. The deterministic verifier remains the source of the simulation result.

## Coverage against the paper

The files in [paper-placeholders](paper-placeholders/) record section, page and purpose for each paper prompt or related interface. PDF pages count the title page as page 1.

| Source material | Placeholder files |
| --- | --- |
| Four prompt examples printed in the paper | [Proxy planning](paper-placeholders/proxy_planning.txt), [dominant action identifier](paper-placeholders/dominant_action_identifier.txt), [cover branch generation](paper-placeholders/cover_branch_generation.txt), [chain fusion](paper-placeholders/chain_fusion.txt) |
| Prompt use described in prose | [Command sanitization](paper-placeholders/command_sanitization.txt) |
| Integration points described in prose | [Planner–verifier feedback](paper-placeholders/planner_verifier_feedback.txt), [target system prompt](paper-placeholders/target_system.txt) |

| Paper location | What is available in the paper | Coverage in this artifact |
| --- | --- | --- |
| §5.2.1, proxy planning | Simplified planning prompt with example slots | The original planner prompt and proxy preparation are unavailable. |
| §5.2.2, command sanitization | Method description and a before/after example | The reference audit serves the reverse review task of making entity references explicit. |
| §5.3.1, dominant-action identification | Example scoring prompt | The consequence review evaluates a supplied record against explicit policy. The release omits adversarial ranking prompts. |
| §5.3.2, cover generation and chain fusion | Separate simplified prompts for branch generation and fusion | The release omits the operational prompts for disguising harmful actions. |
| §5.4, rule-based verifier | Symbolic preconditions, effects and state transitions | The verifier requires executable rules. A textual prompt cannot implement these checks. |
| §5.4.1, planner–verifier feedback | Description of the feedback loop | The report template consumes an existing verifier result. Automated replanning is outside its scope. |
| §6, platform integration | Implementations using ProgPrompt, VirtualHome and xArm | Target-system prompt files and executable adapters are unavailable. |

The [tabletop verifier](../demo/tabletop.py) checks recorded actions using deterministic rules. Goal labels and final-state assessments are optional model annotations for this companion.
