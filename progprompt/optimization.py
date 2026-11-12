"""Bounded optimization and repair for three fixed ordinary tabletop transfers.

The search uses only the symbolic inspect/pick/place transition rules. It never
loads prompts, changes a scene or goal, or uses a task's reference action list.
"""

import json
from collections import deque
from copy import deepcopy
from pathlib import Path

from verifier import tabletop


TASK_DIRECTORY = Path(__file__).resolve().parents[1] / "tasks"
TASK_FILES = {
    "tidy_cup_01": "cup_to_tray.json",
    "agentsafe_normal_apple_counter_local": "apple_to_counter.json",
    "tidy_cup_counter_01": "cup_to_counter.json",
}
MAX_ACTIONS = 64
_PRIMITIVES = ("inspect", "pick", "place")


def _same_json(left, right):
    """Compare report values without accepting True as 1, tuples as arrays, etc."""
    if type(left) is not type(right):
        return False
    if isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], value) for key, value in right.items())
    if isinstance(right, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def _prepare(bundle, actions):
    task_id = bundle.get("task_id") if isinstance(bundle, dict) else None
    if not isinstance(task_id, str) or task_id not in TASK_FILES:
        raise ValueError("Expected one of the three published ordinary transfer task IDs.")
    canonical = json.loads((TASK_DIRECTORY / TASK_FILES[task_id]).read_text(encoding="utf-8"))
    if canonical.get("task_id") != task_id:
        raise ValueError("The published task file does not match its registered task ID.")
    for field in ("scene", "goal"):
        if not _same_json(bundle.get(field), canonical[field]):
            raise ValueError(f"The {field} must exactly match the published {task_id} task.")
    # Optional prose and bundle.actions are deliberately excluded from planning.
    bound = {"task_id": task_id, "scene": deepcopy(bundle["scene"]), "goal": deepcopy(bundle["goal"])}
    initial = tabletop.verify_task({**bound, "actions": []})
    if any(error["phase"] != "goal" for error in initial["errors"]):
        raise ValueError("The published initial scene and goal are not a valid ordinary transfer.")
    transfer = tabletop._validate_scene(bound["scene"])
    if type(actions) is not list or len(actions) > MAX_ACTIONS:
        raise ValueError(f"Expected an action array with at most {MAX_ACTIONS} records.")
    for index, action in enumerate(actions):
        if (type(action) is not dict or type(action.get("action")) is not str
                or action["action"] not in _PRIMITIVES):
            raise ValueError(f"Action {index} must be inspect, pick or place.")
        name = action["action"]
        expected = {"action", "object", "target"} if name == "place" else {"action", "object"}
        if action.keys() != expected:
            raise ValueError(f"Action {index} requires exactly {sorted(expected)}.")
        if type(action["object"]) is not str or action["object"] != transfer.item_id:
            raise ValueError(f"Action {index} is outside the fixed task object.")
        if name == "place" and (type(action["target"]) is not str or action["target"] != transfer.destination_id):
            raise ValueError(f"Action {index} is outside the fixed task destination.")
    copied = deepcopy(actions)
    return bound, copied, transfer, tabletop.verify_task({**bound, "actions": copied})


def _goal_met(scene, transfer):
    return (scene[transfer.item]["on"] == transfer.destination_id
            and scene[transfer.destination]["occupied"]
            and scene["arm"]["held"] is None)


def _search(bound, actions, transfer, *, repair):
    """Find a shortest trace retaining all supplied records in this search.

    Equal primitive records are indistinguishable to the transition system; the
    earliest remaining original index identifies each occurrence for the audit.
    Repair permits at most one additional pick and one additional place. With
    fixed original count, shortest length also means fewest inserted actions.
    """
    groups = [[index for index, action in enumerate(actions) if action["action"] == name]
              for name in _PRIMITIVES]
    counts = tuple(len(group) for group in groups)
    start = deepcopy(bound["scene"])
    queue = deque([(start, counts, (0, 0), [], [])])
    visited = set()
    while queue:
        scene, remaining, inserted, candidate, indices = queue.popleft()
        key = (json.dumps(scene, sort_keys=True), remaining, inserted)
        if key in visited:
            continue
        visited.add(key)
        if not any(remaining) and _goal_met(scene, transfer):
            return candidate, indices
        if len(candidate) >= MAX_ACTIONS:
            continue
        options = []
        for primitive, count in enumerate(remaining):
            if count:
                source = groups[primitive][counts[primitive] - count]
                options.append((source, primitive, actions[source]))
        # Prefer existing records in their input order when several moves are legal.
        options.sort(key=lambda choice: choice[0])
        if repair:
            for primitive in (1, 2):
                if inserted[primitive - 1] == 0:
                    action = {"action": _PRIMITIVES[primitive], "object": transfer.item_id}
                    if primitive == 2:
                        action["target"] = transfer.destination_id
                    options.append((None, primitive, action))
        for source, primitive, action in options:
            updated = deepcopy(scene)
            try:
                tabletop._step(updated, action, transfer)
            except (ValueError, tabletop.RuleViolation):
                continue
            next_remaining = list(remaining)
            next_inserted = list(inserted)
            if source is None:
                next_inserted[primitive - 1] += 1
            else:
                next_remaining[primitive] -= 1
            queue.append((updated, tuple(next_remaining), tuple(next_inserted),
                          candidate + [deepcopy(action)], indices + [source]))
    return None


def _changes(original, candidate, sources):
    changes = []
    retained = {index for index in sources if index is not None}
    for index, action in enumerate(original):
        if index not in retained:
            changes.append({"operation": "remove", "original_index": index, "action": deepcopy(action),
                            "reason": "inspect_has_no_symbolic_state_effect"})
    existing_order = [index for index in sources if index is not None]
    if existing_order != sorted(existing_order):
        changes.append({"operation": "reorder", "original_indices": sorted(existing_order),
                        "candidate_original_indices": existing_order,
                        "reason": "satisfy_fixed_action_preconditions"})
    for index, source in enumerate(sources):
        if source is None:
            changes.append({"operation": "insert", "candidate_index": index, "action": deepcopy(candidate[index]),
                            "reason": "missing_fixed_transfer_primitive"})
    return changes


def _report(bound, original, candidate, before, after, status, reason, changes, sources):
    equivalent = (before["status"] == "passed" and after["status"] == "passed"
                  and _same_json(before["final_state"], after["final_state"]))
    return {"task_id": bound["task_id"], "status": status, "reason": reason,
            "goal": deepcopy(bound["goal"]), "original_actions": deepcopy(original),
            "candidate_actions": deepcopy(candidate), "candidate_original_indices": list(sources),
            "before_verifier": before, "verifier": after, "equivalent": equivalent,
            "changes": changes, "search": {"method": "bounded_breadth_first", "max_actions": MAX_ACTIONS,
                                           "inserted_actions": list(sources).count(None)}}


def optimize_actions(bundle, actions):
    """Remove only state-free inspections from an already successful trace.

    Existing pick/place records may be legally reordered by search, never added
    or removed. Both verifier results must pass with an identical complete final
    state. A failed input is left unchanged for the explicit repair interface.
    """
    bound, original, transfer, before = _prepare(bundle, actions)
    if before["status"] != "passed":
        return _report(bound, original, original, before, deepcopy(before), "unchanged",
                       "requires_verifier_repair", [], range(len(original)))
    retained = [(index, action) for index, action in enumerate(original) if action["action"] != "inspect"]
    outcome = _search(bound, [action for _, action in retained], transfer, repair=False)
    if outcome is None:
        return _report(bound, original, original, before, deepcopy(before), "rejected",
                       "no_bounded_equivalent_trace", [], range(len(original)))
    candidate, local_sources = outcome
    sources = [retained[index][0] for index in local_sources]
    after = tabletop.verify_task({**bound, "actions": candidate})
    if after["status"] != "passed" or not _same_json(before["final_state"], after["final_state"]):
        return _report(bound, original, original, before, deepcopy(before), "rejected",
                       "candidate_not_equivalent", [], range(len(original)))
    changes = _changes(original, candidate, sources)
    return _report(bound, original, candidate, before, after, "optimized" if changes else "unchanged",
                   "removed_state_free_inspections" if changes else "already_minimal", changes, sources)


def repair_actions(bundle, actions, feedback):
    """Use a freshly verified ordinary trace to permit a bounded explicit repair.

    Feedback must exactly match verify_task for these inputs; a supplied passed
    verdict is never trusted. No original action is deleted. Missing pick/place
    operations may be inserted, and existing records may be legally reordered.
    """
    bound, original, transfer, before = _prepare(bundle, actions)
    if not _same_json(feedback, before):
        raise ValueError("Feedback does not exactly match verify_task for this task and these actions.")
    if before["status"] == "passed":
        return _report(bound, original, original, before, deepcopy(before), "unchanged",
                       "already_passed", [], range(len(original)))
    outcome = _search(bound, original, transfer, repair=True)
    if outcome is None:
        return _report(bound, original, original, before, deepcopy(before), "rejected",
                       "no_bounded_legal_repair_preserving_input_actions", [], range(len(original)))
    candidate, sources = outcome
    after = tabletop.verify_task({**bound, "actions": candidate})
    if after["status"] != "passed":
        return _report(bound, original, original, before, deepcopy(before), "rejected",
                       "candidate_failed_verification", [], range(len(original)))
    return _report(bound, original, candidate, before, after, "repaired", "fixed_transfer_preconditions_and_goal",
                   _changes(original, candidate, sources), sources)
