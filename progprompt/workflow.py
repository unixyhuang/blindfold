"""Audited optimization and finite feedback repair for three ordinary transfers."""

import ast
import json
from copy import deepcopy
from pathlib import Path

from progprompt.feedback import expected_feedback
from progprompt.optimization import optimize_actions, repair_actions
from progprompt.runtime import check_program
from verifier.tabletop import verify_task


def _linear_actions(program):
    """Read all actions, including an unexecuted suffix, without dropping assertions."""
    function = ast.parse(program).body[0]
    body = function.body[1:] if ast.get_docstring(function) is not None else function.body
    actions = []
    for statement in body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            return None
        call = statement.value
        # check_program has already validated every name and literal argument.
        if not isinstance(call.func, ast.Name) or call.func.id not in {"inspect", "pick", "place"}:
            return None
        action = {"action": call.func.id, "object": call.args[0].value}
        if call.func.id == "place":
            action["target"] = call.args[1].value
        actions.append(action)
    return actions


def actions_program(bundle, actions):
    lines = ["def plan():"]
    for action in actions:
        arguments = [action["object"]] + ([action["target"]] if action["action"] == "place" else [])
        lines.append(f"    {action['action']}({', '.join(json.dumps(value) for value in arguments)})")
    item, destination = bundle["goal"]["on"]
    lines.extend([f"    assert on({json.dumps(item)}, {json.dumps(destination)})", "    assert hand_empty()"])
    return "\n".join(lines) + "\n"


def optimize_plan(bundle, initial_plan, *, max_repairs=2):
    """Recheck source, repair eligible action failures, then optimize and recheck.

    Failed programs with assertions or control flow are never reduced to a trace
    prefix. Only a fully parsed, action-only failed function can supply a complete
    action sequence for repair. All original program diagnostics are retained.
    """
    if type(max_repairs) is not int or not 0 <= max_repairs <= 3:
        raise ValueError("--max-repairs must be an integer from 0 to 3.")
    if not isinstance(initial_plan, dict):
        raise ValueError("Expected a planner report or action input object.")
    if not isinstance(bundle, dict):
        raise ValueError("Expected a published ordinary task bundle.")
    result = {"task_id": bundle.get("task_id"), "status": "rejected", "termination": None,
              "max_repairs": max_repairs, "repairs_used": 0, "initial_plan": deepcopy(initial_plan),
              "source_verifier": None, "action_source": None, "initial_actions": None,
              "action_verifier": None, "attempts": [],
              "optimization": None, "final_plan": None}
    program = initial_plan.get("program")
    if program is not None:
        checked = check_program(program, bundle)
        result["source_verifier"] = checked
        if checked["status"] == "invalid_program" or any(error["phase"] == "input" for error in checked["errors"]):
            result["termination"] = "invalid_source_program"
            return result
        if checked["status"] != "passed":
            if any(error["phase"] == "assertion" for error in checked["errors"]):
                result["termination"] = "failed_assertion_preserved"
                return result
            if any(error["phase"] not in {"action", "goal"} for error in checked["errors"]):
                result["termination"] = "source_preconditions_not_validated"
                return result
            actions = _linear_actions(program)
            if actions is None:
                result["termination"] = "failed_program_requires_action_only_body"
                return result
            result["action_source"] = "complete_static_action_only_program"
        else:
            actions = checked["actions"]
            result["action_source"] = "verified_execution_path"
    else:
        actions = deepcopy(initial_plan.get("actions"))
        result["action_source"] = "explicit_actions"
    # This also enforces exact scene/goal identity and fixed primitive arguments.
    try:
        preliminary = optimize_actions(bundle, actions)
    except ValueError as error:
        result.update(termination="invalid_task_or_actions", error=str(error))
        return result
    current = preliminary["before_verifier"]
    result.update(initial_actions=deepcopy(actions), action_verifier=deepcopy(current))
    if result["source_verifier"] is None:
        result["source_verifier"] = deepcopy(current)
    seen = {json.dumps(actions, sort_keys=True)}
    while current["status"] != "passed":
        if result["repairs_used"] >= max_repairs:
            result.update(status="repair_exhausted", termination="repair_limit")
            return result
        feedback = deepcopy(current)
        repair = repair_actions(bundle, actions, feedback)
        result["repairs_used"] += 1
        attempt = {"iteration": result["repairs_used"], "input_actions": deepcopy(actions),
                   "verifier": feedback, "feedback": expected_feedback(feedback), "repair": repair}
        result["attempts"].append(attempt)
        candidate = repair["candidate_actions"]
        # The orchestrator independently rechecks the candidate; it does not trust a repair verdict.
        verified = verify_task({**bundle, "actions": candidate})
        attempt["candidate_verifier"] = deepcopy(verified)
        if verified["status"] == "invalid_input":
            result["termination"] = "invalid_repair_candidate"
            return result
        if repair["status"] == "rejected":
            result["termination"] = repair["reason"]
            return result
        fingerprint = json.dumps(candidate, sort_keys=True)
        if fingerprint in seen:
            result["termination"] = "no_progress"
            return result
        seen.add(fingerprint)
        actions, current = deepcopy(candidate), verified
    optimized = optimize_actions(bundle, actions)
    result["optimization"] = optimized
    if optimized["status"] == "rejected" or not optimized["equivalent"]:
        result["termination"] = "optimization_not_equivalent"
        return result
    final_program = actions_program(bundle, optimized["candidate_actions"])
    final = check_program(final_program, bundle)
    final.update(program=final_program, source="ordinary_transfer_workflow")
    result["final_plan"] = final
    if final["status"] != "passed":
        result["termination"] = "final_program_verification_failed"
        return result
    result.update(status="ready", termination="verified_after_optimization")
    return result


def load_plan(args, bundle):
    if getattr(args, "actions", None):
        actions = json.loads(args.actions.read_text(encoding="utf-8-sig"))
        return {**verify_task({**bundle, "actions": actions}), "actions": actions, "source": "supplied_actions"}
    if args.recorded:
        return {**verify_task(bundle), "actions": deepcopy(bundle["actions"]), "source": "recorded_reference"}
    if args.model:
        from progprompt.cli import generate_plan
        return generate_plan(bundle, args.model, device=args.device,
                             max_new_tokens=args.max_new_tokens, input_format=args.input_format)
    program = args.program.read_text(encoding="utf-8-sig")
    return {**check_program(program, bundle), "program": program, "source": "saved_program"}


def add_arguments(parser):
    from progprompt.cli import TASKS
    parser.add_argument("--task", choices=sorted(TASKS), default="cup_to_counter")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--program", type=Path)
    source.add_argument("--actions", type=Path, help="JSON array of ordinary task actions.")
    source.add_argument("--model", type=Path)
    source.add_argument("--recorded", action="store_true")
    parser.add_argument("--max-repairs", type=int, default=2, help="Maximum action repair attempts, from 0 to 3.")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--input-format", choices=["chat", "completion"], default="chat")
    parser.add_argument("--output-dir", type=Path, required=True)


def run(args):
    from progprompt.cli import ROOT, TASKS
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Choose an empty --output-dir for each optimization run.")
    bundle = json.loads((ROOT / "tasks" / TASKS[args.task]).read_text(encoding="utf-8"))
    initial = load_plan(args, bundle)
    report = optimize_plan(bundle, initial, max_repairs=args.max_repairs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "workflow.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if "program" in initial:
        (args.output_dir / "original-plan.py").write_text(initial["program"], encoding="utf-8")
    if report["status"] == "ready":
        (args.output_dir / "plan.py").write_text(report["final_plan"]["program"], encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ready" else 1
