"""Check a fixed symbolic transfer: empty cup to tray, or whole apple to counter.

The bundle's optional prose fields are descriptive. Only the structured scene,
fixed goal and action records participate in verification. No I/O is performed.
"""
from copy import deepcopy
from typing import NamedTuple


TABLE = "table_1"


class Transfer(NamedTuple):
    item: str
    destination: str
    item_id: str
    destination_id: str


CUP = Transfer("cup", "tray", "cup_1", "tray_1")
APPLE = Transfer("apple", "counter", "apple_1", "counter_1")


class RuleViolation(Exception):
    def __init__(self, rule_id, message):
        super().__init__(message)
        self.rule_id = rule_id


def _fields(record, names, label):
    if not isinstance(record, dict) or record.keys() != set(names):
        raise ValueError(f"{label} requires exactly these fields: {', '.join(names)}.")


def _validate_scene(scene):
    if not isinstance(scene, dict):
        raise ValueError("scene must be a JSON object.")
    transfer = APPLE if "apple" in scene else CUP
    _fields(scene, (transfer.item, transfer.destination, "arm"), "scene")
    item, dest, arm = scene[transfer.item], scene[transfer.destination], scene["arm"]
    if transfer == CUP:
        _fields(item, ("id", "on", "empty", "temperature"), "scene.cup")
        _fields(dest, ("id", "on", "occupied"), "scene.tray")
        if type(item["empty"]) is not bool or not isinstance(dest["on"], str):
            raise ValueError("cup.empty must be a boolean and tray.on must be a support ID.")
    else:
        _fields(item, ("id", "on", "condition", "temperature"), "scene.apple")
        _fields(dest, ("id", "occupied"), "scene.counter")
        if not isinstance(item["condition"], str):
            raise ValueError("apple.condition must be a string.")
    _fields(arm, ("held", "reachable"), "scene.arm")
    if type(dest["occupied"]) is not bool:
        raise ValueError("occupied must be a JSON boolean.")
    if not all(isinstance(field, str) for field in
               (item["id"], dest["id"], item["on"], item["temperature"])):
        raise ValueError("IDs, initial supports and temperature must be strings.")
    if arm["held"] is not None and not isinstance(arm["held"], str):
        raise ValueError("held must be an entity ID or null.")
    reach = arm["reachable"]
    if not isinstance(reach, list) or any(entity not in (transfer.item_id, transfer.destination_id)
                                          for entity in reach):
        raise ValueError("reachable must be an array of IDs from the fixed scene.")
    if len(set(reach)) != len(reach):
        raise ValueError("reachable must contain unique entity IDs.")
    return transfer


def _check_start(scene, transfer):
    item, dest, arm = scene[transfer.item], scene[transfer.destination], scene["arm"]
    if item["id"] != transfer.item_id or dest["id"] != transfer.destination_id:
        raise RuleViolation("scene_entities", "Entity IDs do not match the fixed task.")
    if item["on"] != TABLE or (transfer == CUP and dest["on"] != TABLE):
        raise RuleViolation("initial_support", "The item and any portable tray must start on table_1.")
    if item["temperature"] != "ambient":
        raise RuleViolation("item_temperature", "The item must be at ambient temperature.")
    if transfer == CUP and not item["empty"]:
        raise RuleViolation("cup_condition", "The cup must be empty.")
    if transfer == APPLE and item["condition"] != "whole":
        raise RuleViolation("apple_condition", "The apple must be whole.")
    if arm["held"] is not None:
        raise RuleViolation("initial_hand_occupied", "The gripper must start empty.")


def _step(scene, action, transfer):
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        raise ValueError("Each action record requires a string action name.")
    name = action["action"]
    if name not in ("inspect", "pick", "place"):
        raise RuleViolation("unsupported_action", "Supported actions are inspect, pick and place.")
    names = ("action", "object", "target") if name == "place" else ("action", "object")
    _fields(action, names, name)
    if action["object"] != transfer.item_id:
        raise RuleViolation("object_scope", f"This task only handles {transfer.item_id}.")

    item, dest, arm = scene[transfer.item], scene[transfer.destination], scene["arm"]
    if name in ("inspect", "pick") and transfer.item_id not in arm["reachable"] and arm["held"] != transfer.item_id:
        raise RuleViolation("item_unreachable", "The item is outside the arm's declared reach.")
    if name == "inspect":
        return
    if name == "pick":
        if arm["held"] is not None:
            raise RuleViolation("hand_occupied", "The gripper already holds an object.")
        if item["on"] != TABLE:
            raise RuleViolation("pickup_support", "This task permits picking the item from table_1.")
        item["on"] = None
        arm["held"] = transfer.item_id
        return

    if action["target"] != transfer.destination_id:
        raise RuleViolation("target_scope", f"This task only places its item on {transfer.destination_id}.")
    if arm["held"] != transfer.item_id:
        raise RuleViolation("item_not_held", "The gripper must hold the named item before placement.")
    if transfer.destination_id not in arm["reachable"]:
        raise RuleViolation("destination_unreachable", "The destination is outside the arm's declared reach.")
    if dest["occupied"]:
        raise RuleViolation("destination_occupied", "The designated placement slot is occupied.")
    arm["held"] = None
    item["on"] = transfer.destination_id
    dest["occupied"] = True


def verify_task(bundle: dict) -> dict:
    """Return a report; commit the simulated result only if the whole task passes."""
    task_id = None
    initial = None
    working = None
    phase = "input"
    index = None
    name = None
    errors = []
    try:
        if not isinstance(bundle, dict):
            raise ValueError("The task bundle must be a JSON object.")
        if not isinstance(bundle.get("task_id"), str) or not bundle["task_id"].strip():
            raise ValueError("task_id must be a non-empty string.")
        task_id = bundle["task_id"]
        transfer = _validate_scene(bundle.get("scene"))
        initial = deepcopy(bundle["scene"])
        if bundle.get("goal") != {"on": [transfer.item_id, transfer.destination_id], "held": None}:
            raise ValueError("The goal must put the task item at its destination with an empty gripper.")
        actions = bundle.get("actions")
        if not isinstance(actions, list):
            raise ValueError("actions must be a JSON array.")
        working = deepcopy(initial)
        phase = "initial_state"
        _check_start(working, transfer)
        phase = "action"
        for index, action in enumerate(actions):
            name = action.get("action") if isinstance(action, dict) else None
            name = name if isinstance(name, str) else None
            _step(working, action, transfer)
        phase, index, name = "goal", None, None
        if (working[transfer.item]["on"] != transfer.destination_id or not working[transfer.destination]["occupied"]
                or working["arm"]["held"] is not None):
            raise RuleViolation("goal_unmet", "The final scene does not satisfy the stated goal.")
        status = "passed"
    except (ValueError, RuleViolation) as error:
        status = "failed" if isinstance(error, RuleViolation) else "invalid_input"
        errors.append({"phase": phase, "action_index": index, "action_name": name,
                       "rule_id": getattr(error, "rule_id", "invalid_input"),
                       "message": str(error)})

    return {"task_id": task_id, "run_id": task_id, "status": status, "index_base": 0,
            "initial_state": initial, "final_state": working if status == "passed" else deepcopy(initial),
            "goal_met": status == "passed", "errors": errors}
