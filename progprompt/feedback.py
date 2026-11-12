"""Render and check read-only feedback from existing verifier reports."""

import json
import math
import re
from copy import deepcopy
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "prompts/progprompt/verifier_feedback.txt"
STATUSES = {"passed", "failed", "invalid_input", "invalid_program", "supported", "contradicted", "unknown", "conflict"}
FIELDS = ("errors", "issues", "checks", "assertions", "goal_met", "index_base", "observed_goal", "reason", "verifier")
TABLETOP_FIELDS = {"task_id", "run_id", "status", "index_base", "initial_state", "final_state", "goal_met", "errors"}


def _json_value(value):
    """Reject Python-only values and non-finite numbers before copying a report."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, dict) and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise ValueError("Feedback requires finite JSON values and string object keys.")


def _task_id(record):
    value = record.get("task_id", record.get("run_id"))
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError("task_id must be a nonempty string or null.")
    if "run_id" in record and record["run_id"] != value:
        raise ValueError("task_id and run_id disagree.")
    if value is None and record["status"] != "invalid_input":
        raise ValueError("A known task ID is required except for input-validation reports.")
    return value


def _diagnostic_list(values, label):
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise ValueError(f"{label} must be an array of diagnostic objects.")
    for item in values:
        if label in {"errors", "issues"}:
            required = "message" if label == "errors" else "rule"
            if not isinstance(item.get(required), str) or not item[required].strip():
                raise ValueError(f"{label} entries require {required}.")
        if label == "assertions":
            if (type(item.get("line")) is not int or item["line"] < 1
                    or item.get("kind") not in ("assert", "guard")
                    or not isinstance(item.get("predicate"), str)
                    or not isinstance(item.get("arguments"), list)
                    or any(not isinstance(arg, str) for arg in item["arguments"])
                    or "value" not in item or item["value"] is not None and type(item["value"]) is not bool):
                raise ValueError("assertions entries require a line, predicate, arguments and observed boolean or null.")
        for key in ("action_index", "step_index", "evidence_step_index"):
            if key in item and item[key] is not None and (type(item[key]) is not int or item[key] < 0):
                raise ValueError(f"{label}.{key} must be a nonnegative integer or null.")
        if "line" in item and item["line"] is not None and (type(item["line"]) is not int or item["line"] < 1):
            raise ValueError(f"{label}.line must be a positive integer or null.")
        for key in ("rule", "rule_id", "message", "predicate", "phase"):
            if key in item and (not isinstance(item[key], str) or not item[key].strip()):
                raise ValueError(f"{label}.{key} must be a nonempty string.")
        if "action_name" in item and item["action_name"] is not None and not isinstance(item["action_name"], str):
            raise ValueError(f"{label}.action_name must be a string or null.")
        if "status" in item and item["status"] not in ("supported", "contradicted", "unknown"):
            raise ValueError(f"{label}.status is not a recognized goal-check verdict.")


def expected_feedback(record):
    """Copy the report's declared diagnostics without interpreting or repairing them."""
    if not isinstance(record, dict):
        raise ValueError("Expected one verifier report object.")
    _json_value(record)
    if not isinstance(record.get("status"), str) or record["status"] not in STATUSES:
        raise ValueError("Unrecognized verifier status.")
    if "task_id" not in record and "run_id" not in record:
        raise ValueError("Expected task_id or run_id from a verifier report.")
    task_id = _task_id(record)
    if not any(key in record for key in ("errors", "issues", "checks", "verifier")):
        raise ValueError("The object has no verifier diagnostic fields.")
    for key in ("errors", "issues", "checks", "assertions"):
        if key in record:
            _diagnostic_list(record[key], key)
    if "goal_met" in record and type(record["goal_met"]) is not bool:
        raise ValueError("goal_met must be a JSON boolean.")
    if "index_base" in record and (type(record["index_base"]) is not int or record["index_base"] not in (0, 1)):
        raise ValueError("index_base must be 0 or 1.")
    if "reason" in record and (not isinstance(record["reason"], str) or not record["reason"].strip()):
        raise ValueError("reason must be a nonempty string.")
    if record["status"] == "passed" and record.get("errors"):
        raise ValueError("A passed report cannot contain errors.")
    if "observed_goal" in record:
        observed = record["observed_goal"]
        if (not isinstance(observed, dict) or set(observed) != {"status", "checks"}
                or observed["status"] not in ("supported", "contradicted", "unknown")):
            raise ValueError("observed_goal must be an observed goal-check report.")
        _diagnostic_list(observed["checks"], "observed_goal.checks")
    nested = record.get("verifier")
    if nested is not None:
        if not isinstance(nested, dict) or set(nested) != TABLETOP_FIELDS:
            raise ValueError("A nested verifier must be a complete tabletop verifier report.")
        nested_feedback = expected_feedback(nested)
        if nested_feedback["task_id"] != task_id or nested["status"] not in {"passed", "failed", "invalid_input"}:
            raise ValueError("The nested verifier does not belong to this task.")
    if record["status"] == "conflict" and (nested is not None or not record.get("reason")):
        raise ValueError("A model conflict report needs a reason and no completed verifier result.")
    diagnostics = {key: deepcopy(record[key]) for key in FIELDS if key in record}
    return {"task_id": task_id, "status": record["status"], "diagnostics": diagnostics}


def render_feedback(record):
    envelope = expected_feedback(record)
    text = TEMPLATE.read_text(encoding="utf-8")
    return text.replace("{{feedback_record_json}}", json.dumps(envelope, ensure_ascii=False), 1)


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Repeated JSON key: {key}.")
        obj[key] = value
    return obj


def _read_json(text):
    def invalid_number(value):
        raise ValueError(f"Non-finite JSON number: {value}.")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=invalid_number)


def run(args):
    """Render the report prompt or verify that a model copied the complete envelope."""
    try:
        record = _read_json(args.record.read_text(encoding="utf-8-sig"))
        expected = expected_feedback(record)
        prompt = render_feedback(record)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "invalid_input", "error": str(error)}))
        return 2
    if args.render:
        print(prompt, end="")
        return 0
    if args.model is None:
        print(json.dumps({"status": "feedback_ready", "feedback": expected}, indent=2, ensure_ascii=False))
        return 0
    from hf_client import generate_text
    try:
        reply = generate_text(prompt, args.model, device=args.device, max_new_tokens=2048)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "model_error", "error": str(error)}))
        return 2
    body = reply.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", body, re.DOTALL | re.IGNORECASE)
    try:
        received = _read_json(fenced.group(1) if fenced else body)
        # Typed JSON comparison prevents True from matching the integer 1.
        matches = json.dumps(received, sort_keys=True, ensure_ascii=False) == json.dumps(expected, sort_keys=True, ensure_ascii=False)
    except ValueError:
        received, matches = None, False
    if not matches:
        print(json.dumps({"status": "feedback_mismatch", "expected": expected, "received": received,
                          "raw_reply": reply}, indent=2, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "feedback_verified", "feedback": expected}, indent=2, ensure_ascii=False))
    return 0
