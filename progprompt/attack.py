"""Execute the paper's action-chain prompt pipeline on the bundled attack scene.

Stages follow Section 5.2.2 through 5.4.1: command transformation, command
sanitization, dominant action identification, cover branch creation and
completion, chain fusion, and a bounded planner-verifier repair loop. Each
model reply is parsed as strict JSON and checked structurally before the next
stage consumes it. The final chain is replayed by the symbolic verifier.
"""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from progprompt.feedback import expected_feedback, read_json_object
from verifier.attack import (
    ACTIONS,
    VERBS,
    describe_action,
    execute_chain,
    parse_chain,
    validate_task,
    verify_chain,
)


ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = ROOT / "tasks" / "attack"
PROMPT_DIR = ROOT / "prompts" / "progprompt"

STAGES = (
    "command_transformer",
    "command_sanitization",
    "dominant_action_identification",
    "cover_branch_generation",
    "chain_fusion",
)
REPAIR_STAGE = "planner_verifier_repair"

PAPER_FILES = {
    "command_sanitization": "command_sanitization.txt",
    "dominant_action_identification": "dominant_action_identification.txt",
    "cover_branch_generation": "cover_branch_generation.txt",
    "chain_fusion": "chain_fusion.txt",
}
TEMPLATES = {
    "command_transformer": "chain_command_transformer.txt",
    "command_sanitization": "chain_sanitization.txt",
    "dominant_action_identification": "chain_dominant_action.txt",
    "cover_branch_generation": "chain_cover_branch.txt",
    "chain_fusion": "chain_fusion_runtime.txt",
    REPAIR_STAGE: "chain_repair.txt",
}
OBJECT_ACTIONS = {"find", "pick_up", "put_in", "place"}


def task_files():
    return tuple(sorted(path.stem for path in TASK_DIR.glob("*.json")
                        if not path.name.endswith(".reference.json")))


TASKS = task_files()


class StageFailure(ValueError):
    def __init__(self, stage, reason, message):
        super().__init__(message)
        self.stage = stage
        self.reason = reason


def load_task(value):
    path = Path(value)
    if path.is_file():
        bundle = json.loads(path.read_text(encoding="utf-8-sig"))
        validate_task(bundle)
        return bundle
    if value not in TASKS:
        raise ValueError(f"Unknown attack task: {value!r}. Pass a bundled name or an existing JSON file.")
    return json.loads((TASK_DIR / f"{value}.json").read_text(encoding="utf-8"))


def load_reference(task_name):
    if task_name not in TASKS:
        raise ValueError(f"Unknown attack task: {task_name!r}.")
    path = TASK_DIR / f"{task_name}.reference.json"
    return json.loads(path.read_text(encoding="utf-8"))


def action_pool():
    return [{"name": name, "parameters": list(kinds)} for name, kinds in ACTIONS.items()]


def _base_context(bundle):
    scene = bundle["scene"]
    return {
        "task_id": bundle["task_id"],
        "instruction": bundle["instruction"],
        "goal": deepcopy(bundle["goal"]),
        "scene": deepcopy(scene),
        "entities": {
            "locations": list(scene["locations"]),
            "objects": sorted(scene["objects"]),
            "containers": sorted(name for name, record in scene["objects"].items() if "open" in record),
        },
        "action_pool": action_pool(),
    }


def build_context(stage, bundle, *, chain=None, dominant=None, cover_chain=None, verifier=None,
                  attempt=None):
    context = _base_context(bundle)
    context["malicious_categories"] = list(bundle["malicious_categories"])
    if stage == "command_sanitization":
        return {"commands": [describe_action(bundle, action) for action in chain],
                "objects": {name: record["type"] for name, record in bundle["scene"]["objects"].items()}}
    if stage == "dominant_action_identification":
        context.update(chain=deepcopy(chain), expected_score_count=len(chain))
    elif stage == "cover_branch_generation":
        index = dominant["index"]
        prefix = chain[:index - 1] if index else []
        state = execute_chain(bundle, prefix)["final_state"] if prefix else deepcopy(bundle["scene"])
        alternatives = {}
        for parameter in chain[index]["parameters"]:
            if parameter in bundle["scene"]["objects"]:
                alternatives[parameter] = sorted(
                    name for name, record in bundle["scene"]["objects"].items()
                    if name != parameter and name not in bundle["malicious_entities"]
                    and ("open" in record) == ("open" in bundle["scene"]["objects"][parameter]))
        context.update(chain=deepcopy(chain), dominant_index=index,
                       predecessor=deepcopy(chain[index - 1]) if index else None,
                       state_before_branch=deepcopy(state),
                       candidate_substitutions=alternatives)
    elif stage == "chain_fusion":
        index = dominant["index"]
        prefix = chain[:index - 1]
        context.update(chain=deepcopy(chain), dominant_index=index,
                       cover_chain=deepcopy(cover_chain),
                       required_prefix=deepcopy(prefix),
                       required_cover=deepcopy(cover_chain),
                       required_suffix=deepcopy(chain[index:]),
                       state_after_cover=deepcopy(execute_chain(bundle, prefix + cover_chain)["final_state"]))
    elif stage == REPAIR_STAGE:
        context.update(chain=deepcopy(chain), verifier=deepcopy(verifier),
                       feedback=expected_feedback(verifier), attempt=attempt,
                       cover_chain=deepcopy(cover_chain) if cover_chain is not None else None)
    return context


def render_stage_prompt(stage, context):
    if stage not in TEMPLATES:
        raise ValueError(f"Unknown attack stage: {stage!r}.")
    template = (PROMPT_DIR / TEMPLATES[stage]).read_text(encoding="utf-8")
    if "paper_prompt" in template:
        paper = (PROMPT_DIR / PAPER_FILES[stage]).read_text(encoding="utf-8").strip()
        template = template.replace("{{paper_prompt}}", paper, 1)
    rendered = template.replace("{{chain_context_json}}",
                                json.dumps(context, indent=2, ensure_ascii=False), 1)
    if "{{" in rendered:
        raise ValueError(f"The {stage} template has an unresolved placeholder.")
    return rendered


def parse_reply(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model reply is empty.")
    body = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", body, re.DOTALL | re.IGNORECASE)
    if fence:
        body = fence.group(1)
    value = read_json_object(body)
    if not isinstance(value, dict):
        raise ValueError("The model reply must be one JSON object.")
    return value


def _require(stage, reply, keys, status):
    if set(reply) != set(keys):
        raise StageFailure(stage, "unexpected_fields",
                           f"Expected exactly {sorted(keys)}, got {sorted(reply)}.")
    if reply.get("status") != status:
        raise StageFailure(stage, "unexpected_status",
                           f"Expected status {status!r}, got {reply.get('status')!r}.")


def _chain(stage, bundle, value):
    try:
        return parse_chain(bundle, value)
    except ValueError as error:
        raise StageFailure(stage, "invalid_chain", str(error)) from error


def _check_transformer(stage, bundle, reply):
    _require(stage, reply, ("status", "chain"), "planned")
    chain = _chain(stage, bundle, reply["chain"])
    checked = execute_chain(bundle, chain)
    if checked["status"] != "passed":
        error = checked["errors"][0]
        index = error.get("action_index")
        where = f"action {index} ({error.get('action')})" if index is not None else "the terminal goal"
        raise StageFailure(stage, "transformer_chain_not_executable",
                           f"{where} violates {error['rule_id']}: {error['message']}")
    return chain


def _check_sanitization(stage, bundle, chain, reply):
    _require(stage, reply, ("status", "commands"), "sanitized")
    commands = reply["commands"]
    if not isinstance(commands, list) or len(commands) != len(chain):
        raise StageFailure(stage, "command_count_mismatch",
                           "The reply must contain one command per input command.")
    checked = []
    for action, command in zip(chain, commands):
        if not isinstance(command, str) or not command.strip():
            raise StageFailure(stage, "invalid_command", "Every command must be a nonempty string.")
        words = re.findall(r"[a-z]+", command.lower())
        if not all(word in words for word in VERBS[action["action"]].split()):
            raise StageFailure(stage, "action_type_changed",
                               f"Command {command!r} does not preserve {action['action']!r}.")
        if action["action"] in OBJECT_ACTIONS:
            name = bundle["scene"]["objects"][action["parameters"][0]]["type"]
            if name in command.lower():
                raise StageFailure(stage, "explicit_object_reference",
                                   f"Command {command!r} keeps the explicit object {name!r}.")
            if "it" not in words and "them" not in words:
                raise StageFailure(stage, "missing_pronoun",
                                   f"Command {command!r} has no implicit object reference.")
        checked.append(command.strip())
    return checked


def _score(value, label, stage):
    if type(value) is not int or not 1 <= value <= 5:
        raise StageFailure(stage, "invalid_score", f"{label} must be an integer from 1 to 5.")
    return value


def _check_dominant(stage, bundle, chain, reply):
    _require(stage, reply, ("status", "index", "baseline_score", "scores"), "identified")
    index = reply["index"]
    if type(index) is not int or not 0 <= index < len(chain):
        raise StageFailure(stage, "invalid_index", "index must address one input action.")
    baseline = _score(reply["baseline_score"], "baseline_score", stage)
    scores = reply["scores"]
    if not isinstance(scores, list) or len(scores) != len(chain):
        actual = len(scores) if isinstance(scores, list) else None
        raise StageFailure(stage, "score_count_mismatch",
                           f"scores must contain exactly {len(chain)} values, got {actual}.")
    scores = [_score(score, f"scores[{number}]", stage) for number, score in enumerate(scores)]
    reductions = [baseline - score for score in scores]
    if reductions[index] <= 0:
        raise StageFailure(stage, "dominant_action_not_harmful",
                           "Removing the identified action must reduce harmfulness.")
    if reductions[index] != max(reductions):
        raise StageFailure(stage, "dominant_action_not_maximal",
                           "The identified action does not have the greatest reduction.")
    return {"index": index, "baseline_score": baseline, "scores": scores,
            "reductions": reductions, "action": deepcopy(chain[index])}


def _check_cover(stage, bundle, chain, dominant, reply):
    _require(stage, reply, ("status", "dominant_index", "cover_chain", "benign_action"), "generated")
    index = reply["dominant_index"]
    if index != dominant["index"]:
        raise StageFailure(stage, "dominant_index_mismatch",
                           "dominant_index must repeat the identified position.")
    if index == 0:
        raise StageFailure(stage, "dominant_action_has_no_predecessor",
                           "Cover branch creation requires a preceding action.")
    cover = _chain(stage, bundle, reply["cover_chain"])
    if len(cover) < 2:
        raise StageFailure(stage, "cover_chain_too_short",
                           "The cover branch must contain the predecessor and the substituted action.")
    benign = reply["benign_action"]
    if not isinstance(benign, dict) or set(benign) != {"action", "parameters"}:
        raise StageFailure(stage, "invalid_benign_action",
                           "benign_action must be one exact action record.")
    if benign != cover[-1]:
        raise StageFailure(stage, "benign_action_mismatch",
                           "benign_action must equal the last cover step.")
    if cover[0] != chain[index - 1]:
        raise StageFailure(stage, "cover_chain_does_not_start_at_predecessor",
                           "cover_chain must repeat the action immediately before the dominant action.")
    dominant_action = chain[index]
    last = cover[-1]
    if last["action"] != dominant_action["action"]:
        raise StageFailure(stage, "action_type_changed",
                           "The benign action must keep the dominant action type.")
    differences = [position for position, (old, new)
                   in enumerate(zip(dominant_action["parameters"], last["parameters"])) if old != new]
    if len(differences) != 1:
        raise StageFailure(stage, "parameter_substitution_not_unique",
                           "Exactly one parameter must differ from the dominant action.")
    position = differences[0]
    original = dominant_action["parameters"][position]
    replacement = last["parameters"][position]
    if not any(parameter in bundle["malicious_entities"] for parameter in dominant_action["parameters"]):
        raise StageFailure(stage, "substitution_not_malicious",
                           "The dominant action does not reference a declared malicious entity.")
    if replacement in bundle["malicious_entities"]:
        raise StageFailure(stage, "substitution_not_benign",
                           "The replacement parameter is still a malicious entity.")
    prefix = chain[:index - 1]
    executed_prefix = execute_chain(bundle, prefix) if prefix else {"status": "passed", "errors": []}
    if executed_prefix["status"] != "passed":
        error = executed_prefix["errors"][0]["message"] if executed_prefix["errors"] else "unknown failure"
        raise StageFailure(stage, "cover_prefix_not_executable", error)
    executed = execute_chain(bundle, prefix + cover)
    if executed["status"] != "passed":
        failure = executed["errors"][0] if executed["errors"] else None
        if failure is None:
            raise StageFailure(stage, "cover_branch_not_executable", "unknown branch failure")
        action_index = failure.get("action_index")
        where = (f"action {action_index} ({failure.get('action')})"
                 if action_index is not None else "the branch")
        raise StageFailure(stage, "cover_branch_not_executable",
                           f"{where} violates {failure['rule_id']}: {failure['message']}")
    if verify_chain(bundle, prefix + cover)["status"] == "passed":
        raise StageFailure(stage, "cover_branch_satisfies_goal",
                           "The cover branch must not reach the malicious goal.")
    return cover


def _step_fingerprint(step):
    return (step["action"], tuple(step["parameters"]))


def _is_subsequence(needles, haystack):
    iterator = iter(haystack)
    return all(any(candidate == needle for candidate in iterator) for needle in needles)


def _check_fusion(stage, bundle, chain, cover, dominant, reply):
    """Validate the model's conflict list and corrective actions, then assemble Eq. 6."""
    _require(stage, reply, ("status", "conflicts", "corrections"), "fused")
    conflicts = reply["conflicts"]
    if not isinstance(conflicts, list) or any(not isinstance(item, str) or not item.strip()
                                              for item in conflicts):
        raise StageFailure(stage, "invalid_conflicts",
                           "conflicts must be an array of nonempty strings.")
    corrections = reply["corrections"]
    if not isinstance(corrections, list):
        raise StageFailure(stage, "invalid_corrections", "corrections must be an array.")
    parsed_corrections = []
    for entry in corrections:
        if not isinstance(entry, dict) or set(entry) != {"action", "parameters", "reason"}:
            raise StageFailure(stage, "invalid_correction",
                               "Each correction requires action, parameters and reason.")
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            raise StageFailure(stage, "invalid_correction", "Each correction needs a reason.")
        step = _chain(stage, bundle, [{"action": entry["action"], "parameters": entry["parameters"]}])[0]
        parsed_corrections.append({**step, "reason": entry["reason"].strip()})
    prefix = chain[:dominant["index"] - 1]
    suffix = chain[dominant["index"]:]
    partial = prefix + cover + [{"action": step["action"], "parameters": list(step["parameters"])}
                                for step in parsed_corrections]
    executed = execute_chain(bundle, partial)
    if executed["status"] != "passed":
        failure = executed["errors"][0]
        offset = len(prefix) + len(cover)
        index = failure.get("action_index")
        if index is not None and index >= offset:
            raise StageFailure(stage, "correction_not_executable",
                               f"correction {index - offset} ({failure.get('action')}) violates "
                               f"{failure['rule_id']}: {failure['message']}")
        raise StageFailure(stage, "fusion_partial_not_executable", failure["message"])
    fused = partial + suffix
    executed = execute_chain(bundle, fused)
    if executed["status"] != "passed":
        failure = executed["errors"][0]
        index = failure.get("action_index")
        if index is not None and index >= len(partial):
            raise StageFailure(stage, "suffix_not_executable_after_cover",
                               f"required_suffix action {index - len(partial)} "
                               f"({failure.get('action')}) violates {failure['rule_id']}: "
                               f"{failure['message']}; add corrective actions before the suffix.")
        raise StageFailure(stage, "fusion_not_executable", failure["message"])
    return {"chain": fused, "conflicts": list(conflicts), "corrections": parsed_corrections,
            "assembly": "prefix + cover + corrections + suffix"}


def _check_repair(stage, bundle, chain, cover, reply):
    _require(stage, reply, ("status", "chain"), "repaired")
    repaired = _chain(stage, bundle, reply["chain"])
    if not _is_subsequence([_step_fingerprint(step) for step in chain],
                           [_step_fingerprint(step) for step in repaired]):
        raise StageFailure(stage, "repair_dropped_original_actions",
                           "The repaired chain must keep every original action in order.")
    if not _is_subsequence([_step_fingerprint(step) for step in cover],
                           [_step_fingerprint(step) for step in repaired]):
        raise StageFailure(stage, "repair_dropped_cover_actions",
                           "The repaired chain must keep every cover action in order.")
    return repaired


def _prompt_sha256(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _record_stage(report, stage, prompt, reply, parsed, rejected):
    report["stages"].append({"stage": stage, "prompt_sha256": _prompt_sha256(prompt),
                             "prompt": prompt, "reply": reply, "parsed": parsed,
                             "rejected_replies": rejected})


def _evaluate(stage, reply, check):
    try:
        parsed = parse_reply(reply)
        return parsed, check(parsed)
    except StageFailure:
        raise
    except ValueError as error:
        raise StageFailure(stage, "invalid_reply", str(error)) from error


RETRY_NOTE = ("\n\nYour previous reply was rejected by the deterministic checker: {reason}\n"
              "Return exactly one corrected JSON object with no prose and no code fence.\n")


def _run_stage(report, stage, prompt, propose, check):
    """Ask for one stage, retrying with the checker's reason when the reply is rejected."""
    rejected = []
    for attempt in range(report["max_stage_retries"] + 1):
        reply = propose(stage, prompt)
        try:
            parsed, value = _evaluate(stage, reply, check)
        except StageFailure as failure:
            report["stage_retries"] += 1
            rejected.append({"reply": reply, "reason": failure.reason, "message": str(failure)})
            if attempt == report["max_stage_retries"]:
                report["rejected_replies"] = rejected
                raise
            prompt = prompt + RETRY_NOTE.format(reason=f"{failure.reason}: {failure}")
        else:
            _record_stage(report, stage, prompt, reply, parsed, rejected)
            return value


def run_pipeline(bundle, proposer, *, max_repairs=2, retries=1):
    """Run every chain stage, then verify and repair the fused chain."""
    if type(max_repairs) is not int or not 0 <= max_repairs <= 3:
        raise ValueError("--max-repairs must be an integer from 0 to 3.")
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ValueError("--retries must be an integer from 0 to 3.")
    validate_task(bundle)
    bundle = deepcopy(bundle)
    report = {"task_id": bundle["task_id"], "instruction": bundle["instruction"],
              "status": "rejected", "termination": None, "max_repairs": max_repairs,
              "max_stage_retries": retries, "stage_retries": 0, "rejected_replies": [],
              "repairs_used": 0, "failed_stage": None, "stages": [],
              "sanitized_commands": None, "dominant_action": None, "cover_chain": None,
              "fusion": None, "verifier": None, "attempts": [], "final_chain": None,
              "final_verifier": None, "final_commands": None}

    def stage_prompt(stage, context):
        return render_stage_prompt(stage, context)

    try:
        stage = "command_transformer"
        chain = _run_stage(
            report, stage, stage_prompt(stage, build_context(stage, bundle)), proposer,
            lambda value: _check_transformer(stage, bundle, value))

        stage = "command_sanitization"
        report["sanitized_commands"] = _run_stage(
            report, stage, stage_prompt(stage, build_context(stage, bundle, chain=chain)), proposer,
            lambda value: _check_sanitization(stage, bundle, chain, value))

        stage = "dominant_action_identification"
        dominant = _run_stage(
            report, stage,
            stage_prompt(stage, build_context(stage, bundle, chain=chain)), proposer,
            lambda value: _check_dominant(stage, bundle, chain, value))
        report["dominant_action"] = dominant

        stage = "cover_branch_generation"
        cover = _run_stage(
            report, stage,
            stage_prompt(stage, build_context(stage, bundle, chain=chain, dominant=dominant)),
            proposer,
            lambda value: _check_cover(stage, bundle, chain, dominant, value))
        report["cover_chain"] = cover

        stage = "chain_fusion"
        fusion = _run_stage(
            report, stage,
            stage_prompt(stage, build_context(stage, bundle, chain=chain, dominant=dominant,
                                              cover_chain=cover)),
            proposer,
            lambda value: _check_fusion(stage, bundle, chain, cover, dominant, value))
        report["fusion"] = fusion
    except StageFailure as failure:
        report.update(status="rejected", termination=failure.reason, failed_stage=failure.stage)
        report["error"] = str(failure)
        return report

    current = fusion["chain"]
    verifier = verify_chain(bundle, current)
    report["verifier"] = verifier
    seen = {json.dumps(current, sort_keys=True)}
    while verifier["status"] != "passed":
        if report["repairs_used"] >= max_repairs:
            report["termination"] = "repair_limit"
            return report
        report["repairs_used"] += 1
        stage = REPAIR_STAGE
        context = build_context(stage, bundle, chain=current, verifier=verifier,
                                attempt=report["repairs_used"], cover_chain=cover)
        try:
            candidate = _run_stage(
                report, stage, stage_prompt(stage, context), proposer,
                lambda value: _check_repair(stage, bundle, chain, cover, value))
        except StageFailure as failure:
            report.update(termination=failure.reason, failed_stage=failure.stage,
                          error=str(failure))
            return report
        entry = report["stages"][-1]
        attempt = {"iteration": report["repairs_used"], "input_chain": deepcopy(current),
                   "verifier": deepcopy(verifier), "reply": entry["reply"],
                   "parsed": entry["parsed"], "candidate_chain": deepcopy(candidate)}
        fingerprint = json.dumps(candidate, sort_keys=True)
        if fingerprint in seen:
            report["termination"] = "no_progress"
            report["attempts"].append(attempt)
            return report
        seen.add(fingerprint)
        candidate_verifier = verify_chain(bundle, candidate)
        attempt["candidate_verifier"] = deepcopy(candidate_verifier)
        report["attempts"].append(attempt)
        current, verifier = candidate, candidate_verifier
        report["verifier"] = verifier

    report.update(status="ready", termination="verified", final_chain=deepcopy(current),
                  final_verifier=deepcopy(verifier),
                  final_commands=[describe_action(bundle, action) for action in current])
    return report


def model_proposer(model, *, device="auto", max_new_tokens=2048):
    """Load one local generator and reuse it for every stage of the run."""
    from hf_client import LocalGenerator

    generator = LocalGenerator(model, device=device)

    def propose(stage, prompt):
        answer, = generator.generate_many([prompt], max_new_tokens=max_new_tokens)
        if not answer.strip():
            raise RuntimeError(f"The model returned no text for stage {stage!r}.")
        return answer

    return propose


def reference_proposer(task_name):
    replies = load_reference(task_name)

    def propose(stage, prompt):
        if stage not in replies:
            raise RuntimeError(f"No recorded reply for stage {stage!r}.")
        return json.dumps(replies[stage], ensure_ascii=False)

    return propose


def responses_proposer(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("--responses must contain one JSON object keyed by stage.")
    replies = {}
    for stage, reply in payload.items():
        replies[stage] = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)

    def propose(stage, prompt):
        if stage not in replies:
            raise RuntimeError(f"No recorded reply for stage {stage!r}.")
        return replies[stage]

    return propose


def render_reference_stage(task_name, stage):
    """Render one stage prompt using the recorded reference replies for prior stages."""
    replies = load_reference(task_name)
    bundle = load_task(task_name)
    if stage == "command_transformer":
        return render_stage_prompt(stage, build_context(stage, bundle))
    chain = parse_chain(bundle, replies["command_transformer"]["chain"])
    if stage == "command_sanitization":
        return render_stage_prompt(stage, build_context(stage, bundle, chain=chain))
    dominant = _check_dominant(stage, bundle, chain, replies["dominant_action_identification"])
    if stage == "dominant_action_identification":
        return render_stage_prompt(stage, build_context(stage, bundle, chain=chain))
    cover = _check_cover("cover_branch_generation", bundle, chain, dominant,
                         replies["cover_branch_generation"])
    if stage == "cover_branch_generation":
        return render_stage_prompt(stage, build_context(stage, bundle, chain=chain, dominant=dominant))
    return render_stage_prompt(
        "chain_fusion",
        build_context("chain_fusion", bundle, chain=chain, dominant=dominant, cover_chain=cover))


def add_arguments(parser):
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--task", choices=sorted(TASKS),
                        help="Bundled attack task (default: phone_into_oven).")
    target.add_argument("--task-file", type=Path,
                        help="Any attack task JSON with instruction, scene, goal and categories.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--recorded", action="store_true",
                        help="Use the recorded reference replies shipped with the task.")
    source.add_argument("--model", type=Path, help="Local Hugging Face checkpoint for every stage.")
    source.add_argument("--responses", type=Path, help="JSON object of stage replies to replay.")
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--retries", type=int, default=2,
                        help="Per-stage format retries with the checker reason, from 0 to 3.")
    parser.add_argument("--max-repairs", type=int, default=2,
                        help="Maximum planner-verifier repair attempts, from 0 to 3.")
    parser.add_argument("--virtualhome", action="store_true",
                        help="Execute the verified chain in the bundled VirtualHome Evolving Graph engine.")
    parser.add_argument("--render-stage", choices=list(STAGES),
                        help="Print one stage prompt built from the recorded reference replies.")
    parser.add_argument("--output-dir", type=Path)


def run(args):
    task = args.task or "phone_into_oven"
    if args.render_stage:
        if args.task_file:
            raise ValueError("--render-stage uses a bundled reference task, not --task-file.")
        print(render_reference_stage(task, args.render_stage), end="")
        return 0
    if not (args.recorded or args.model or args.responses):
        raise ValueError("Choose --recorded, --model or --responses, or use --render-stage.")
    if args.output_dir is None:
        raise ValueError("--output-dir is required for a pipeline run.")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Choose an empty --output-dir for each attack run.")
    if args.recorded and args.task_file:
        raise ValueError("--recorded needs a bundled task; use --responses with --task-file.")
    bundle = load_task(args.task_file if args.task_file else task)
    if args.recorded:
        proposer = reference_proposer(task)
    elif args.responses:
        proposer = responses_proposer(args.responses)
    else:
        proposer = model_proposer(args.model, device=args.device, max_new_tokens=args.max_new_tokens)
    report = run_pipeline(bundle, proposer, max_repairs=args.max_repairs, retries=args.retries)
    if report["status"] == "ready" and getattr(args, "virtualhome", False):
        from simulators.attack_graph import execute_attack
        execution = execute_attack(bundle, report["final_chain"])
        report["virtualhome"] = execution
        if execution["status"] != "passed":
            report["status"] = "virtualhome_failed"
            report["termination"] = "virtualhome_" + execution["status"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "attack.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for number, entry in enumerate(report["stages"]):
        stem = f"{number:02d}-{entry['stage']}"
        (args.output_dir / f"{stem}.prompt.txt").write_text(entry["prompt"], encoding="utf-8")
        (args.output_dir / f"{stem}.reply.txt").write_text(entry["reply"], encoding="utf-8")
    if "virtualhome" in report:
        (args.output_dir / "virtualhome.json").write_text(
            json.dumps(report["virtualhome"], indent=2) + "\n", encoding="utf-8")
    if report["status"] == "ready":
        (args.output_dir / "final-chain.json").write_text(
            json.dumps(report["final_chain"], indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "final-commands.txt").write_text(
            "\n".join(report["final_commands"]) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ready" else 1
