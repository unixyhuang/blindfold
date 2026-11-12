"""Check model-proposed event orders for the two bundled tabletop transfers."""

import json
import re
from pathlib import Path

from verifier.tabletop import verify_task


TASK_DIR = Path(__file__).resolve().parents[1] / "tasks"
TEMPLATE = TASK_DIR.parent / "prompts/progprompt/tabletop_chain_fusion.txt"
TASK_FILES = {
    "tidy_cup_01": "cup_to_tray.json",
    "agentsafe_normal_apple_counter_local": "apple_to_counter.json",
}
EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")


def prepare_merge(bundle, fragments):
    """Return the fixed scene and goal and two validated event fragments."""
    task_id = bundle.get("task_id") if isinstance(bundle, dict) else None
    if not isinstance(task_id, str) or task_id not in TASK_FILES:
        raise ValueError("Expected the task ID of a bundled tabletop transfer.")
    task = json.loads((TASK_DIR / TASK_FILES[task_id]).read_text(encoding="utf-8"))
    if not bundle.keys() <= task.keys():
        raise ValueError("The task bundle contains unexpected fields.")
    # JSON serialization distinguishes a boolean state from a numeric 0 or 1.
    for field in ("scene", "goal"):
        try:
            supplied = json.dumps(bundle.get(field), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Expected JSON for {field}.") from exc
        if supplied != json.dumps(task[field], sort_keys=True):
            raise ValueError(f"The {field} does not match the bundled {task_id} task.")
    if not isinstance(fragments, list) or len(fragments) != 2:
        raise ValueError("Expected two arrays of tabletop events.")
    item, target = task["goal"]["on"]
    events = {}
    checked = []
    for fragment in fragments:
        if not isinstance(fragment, list):
            raise ValueError("Each fragment must be an array of events.")
        seen = set()
        sequence = []
        for event in fragment:
            if not isinstance(event, dict) or event.get("action") not in ("inspect", "pick", "place"):
                raise ValueError("Each event requires an inspect, pick or place action.")
            fields = {"id", "action", "object"}
            if event["action"] == "place":
                fields.add("target")
            if event.keys() != fields:
                raise ValueError(f"The {event['action']} event requires exactly {sorted(fields)}.")
            event_id = event["id"]
            if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
                raise ValueError("Expected a short event ID matching " + EVENT_ID.pattern + ".")
            if event["object"] != item or ("target" in event and event["target"] != target):
                raise ValueError(f"Event {event_id} is outside this task's object or destination.")
            if event_id in seen:
                raise ValueError(f"Event {event_id} occurs twice in one fragment.")
            if event_id in events and events[event_id] != event:
                raise ValueError(f"Shared event {event_id} has conflicting action records.")
            seen.add(event_id)
            events[event_id] = event
            sequence.append(dict(event))
        checked.append(sequence)
    return {"task_id": task_id, "scene": task["scene"], "goal": task["goal"], "fragments": checked}


def render_merge_prompt(bundle, fragments):
    """Render one row per event and derive immediate predecessors from both logs."""
    record = prepare_merge(bundle, fragments)
    events = {e["id"]: {k: v for k, v in e.items() if k != "id"}
              for fragment in record["fragments"] for e in fragment}
    fragments_by_id = [[e["id"] for e in fragment] for fragment in record["fragments"]]
    for event in events.values():
        event["after"] = []
    for fragment in fragments_by_id:
        for earlier, later in zip(fragment, fragment[1:]):
            if earlier not in events[later]["after"]:
                events[later]["after"].append(earlier)
    model_input = {**record, "fragments": fragments_by_id, "events": events}
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count("{{merge_record_json}}") != 1:
        raise ValueError("The tabletop merge template must contain exactly one {{merge_record_json}} field.")
    return template.replace("{{merge_record_json}}", json.dumps(model_input, indent=2), 1)


def check_merge(bundle, fragments, proposal):
    """Check event coverage, fragment ordering, and the existing tabletop rules."""
    report = {"task_id": None, "status": "invalid_input", "order": [], "actions": [],
              "verifier": None, "errors": []}
    try:
        record = prepare_merge(bundle, fragments)
        report["task_id"] = record["task_id"]
        if not isinstance(proposal, dict):
            raise ValueError("Expected a JSON proposal object.")
        if proposal.get("status") == "conflict":
            reason = proposal.get("reason")
            if proposal.keys() != {"status", "reason"} or not isinstance(reason, str) or not reason.strip():
                raise ValueError("A conflict proposal requires a reason string.")
            report.update(status="conflict", reason=reason.strip())
            return report
        if proposal.get("status") != "merged" or proposal.keys() != {"status", "order"}:
            raise ValueError("A merged proposal requires exactly status and order.")
        order = proposal["order"]
        if not isinstance(order, list) or any(not isinstance(e, str) for e in order):
            raise ValueError("The proposed order must be an array of event IDs.")
    except ValueError as exc:
        report["errors"].append({"rule_id": "invalid_input", "message": str(exc)})
        return report

    report.update(status="failed", order=list(order))
    events = {e["id"]: e for fragment in record["fragments"] for e in fragment}
    positions = {event_id: i for i, event_id in enumerate(order)}
    if positions.keys() != events.keys() or len(positions) != len(order):
        report["errors"].append({"rule_id": "event_coverage", "message": "Each input ID must appear exactly once.",
                                 "missing": sorted(events.keys() - positions.keys()),
                                 "unexpected": sorted(positions.keys() - events.keys())})
        return report
    for number, fragment in enumerate(record["fragments"]):
        indices = [positions[e["id"]] for e in fragment]
        if indices != sorted(indices):
            report["errors"].append({"rule_id": "fragment_order", "fragment_index": number,
                                     "message": "The proposed order changes the order within this fragment."})
            return report
    actions = [{key: value for key, value in events[e].items() if key != "id"} for e in order]
    checked = verify_task({k: record[k] for k in ("task_id", "scene", "goal")} | {"actions": actions})
    report.update(status=checked["status"], actions=actions, verifier=checked, errors=checked["errors"])
    return report
