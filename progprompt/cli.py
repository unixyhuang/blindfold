"""Render situated prompts, generate a local plan, and replay a saved program."""

import hashlib
import json
import re
from pathlib import Path
from string import Template

from progprompt.runtime import check_program
from verifier.tabletop import _validate_scene


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "prompts" / "progprompt"
TASKS = {"cup_to_tray": "cup_to_tray.json", "apple_to_counter": "apple_to_counter.json",
         "cup_to_counter": "cup_to_counter.json"}


def render_prompt(bundle):
    scene = bundle["scene"]
    transfer = _validate_scene(scene)
    objects = set()
    for entity in scene.values():
        for field in ("id", "on"):
            if entity.get(field):
                objects.add(entity[field])
    query = Template((TEMPLATES / "query.txt").read_text(encoding="utf-8")).substitute(
        objects=json.dumps(sorted(objects)), scene=json.dumps(scene, sort_keys=True),
        items=json.dumps([transfer.item_id]), destinations=json.dumps([transfer.destination_id]),
        instruction=bundle["instruction"],
        task_function="_".join(re.findall(r"[a-z0-9]+", bundle["instruction"].lower())),
    )
    header = (TEMPLATES / "header.txt").read_text(encoding="utf-8")
    demos = (TEMPLATES / "demonstrations.txt").read_text(encoding="utf-8")
    return "\n\n".join(part.strip() for part in (header, demos, query)) + "\n    "


def as_program(response):
    """Keep the target function's continuation and restore the prompt's indentation."""
    # A completion can start another demonstration or scene after the target body.
    # Use the prompt's top-level section markers, independent of the goal or actions.
    boundary = r"\n(?=def |objects\s*=|# Demonstration:|# Current task\b)"
    body = re.split(boundary, "    " + response, maxsplit=1)[0]
    return "def plan():\n" + body.rstrip() + "\n"


def render_chat_prompt(bundle):
    template = Template((TEMPLATES / "tabletop_chat.txt").read_text(encoding="utf-8"))
    return template.substitute(planning_context=render_prompt(bundle)).rstrip()


def generate_plan(bundle, model, *, device="auto", max_new_tokens=256, input_format="chat"):
    from hf_client import generate_text
    if input_format not in {"chat", "completion"}:
        raise ValueError("--input-format must be chat or completion.")
    prompt = render_chat_prompt(bundle) if input_format == "chat" else render_prompt(bundle)
    response = generate_text(prompt, model, device=device, max_new_tokens=max_new_tokens,
                             completion=input_format == "completion")
    if input_format == "chat":
        from progprompt.benchmark import extract_program
        program, envelope = extract_program(response)
    else:
        program, envelope = as_program(response), "continuation"
    report = check_program(program, bundle)
    report.update(source="model_generated", program=program, raw_completion=response, response_format=envelope)
    report["generation"] = {"model_directory": str(model), "max_new_tokens": max_new_tokens,
                            "decoding": "greedy", "input_format": "chat_template" if input_format == "chat" else "causal_completion",
                            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
    return report


def add_arguments(parser):
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("check-prompts", help="Inspect prompt resources and paper workflow readiness without loading a model.")
    render = commands.add_parser("render", help="Print the exact prompt sent to the model.")
    generate = commands.add_parser("generate", help="Generate a program locally and check it.")
    replay = commands.add_parser("replay", help="Check a saved program on its symbolic scene.")
    feedback = commands.add_parser("feedback", help="Report the verifier's diagnostics for an existing run.")
    feedback.add_argument("--record", type=Path, required=True, help="Single verifier or planner report JSON.")
    feedback_mode = feedback.add_mutually_exclusive_group()
    feedback_mode.add_argument("--render", action="store_true", help="Print the populated feedback prompt.")
    feedback_mode.add_argument("--model", type=Path, help="Render and validate a local model's diagnostic report.")
    feedback.add_argument("--device", choices=["auto", "cpu"], default="auto")
    fuse = commands.add_parser("fuse", help="Reconcile two fragments of one tabletop transfer.")
    fuse.add_argument("--fragments", type=Path, required=True, help="JSON array containing two event lists.")
    mode = fuse.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true", help="Print the populated reconciliation prompt.")
    mode.add_argument("--model", type=Path, help="Propose an event order with a local Hugging Face checkpoint.")
    fuse.add_argument("--device", choices=["auto", "cpu"], default="auto")
    from progprompt import benchmark
    benchmark.add_arguments(commands.add_parser("benchmark", help="Generate and verify SafeAgentBench plans."))
    for command in (render, generate, replay):
        command.add_argument("--task", choices=sorted(TASKS), default="cup_to_tray")
    fuse.add_argument("--task", choices=["apple_to_counter", "cup_to_tray"], default="cup_to_tray")
    generate.add_argument("--model", type=Path, required=True, help="Local Hugging Face checkpoint.")
    generate.add_argument("--device", choices=["auto", "cpu"], default="auto")
    generate.add_argument("--max-new-tokens", type=int, default=256)
    for command in (render, generate):
        command.add_argument("--input-format", choices=["chat", "completion"], default="chat",
                             help="Chat-formatted complete function (default), or raw causal continuation.")
    generate.add_argument("--save-program", type=Path, help="Save the program text for replay.")
    replay.add_argument("--program", required=True, type=Path, help="Path to a plan containing def plan().")


def run(args):
    if args.operation == "check-prompts":
        from progprompt import resources
        return resources.run(args)
    if args.operation == "feedback":
        from progprompt import feedback
        return feedback.run(args)
    if args.operation == "benchmark":
        from progprompt import benchmark
        return benchmark.run(args)
    bundle = json.loads((ROOT / "tasks" / TASKS[args.task]).read_text(encoding="utf-8"))
    if args.operation == "fuse":
        from progprompt.tabletop_merge import check_merge, render_merge_prompt
        fragments = json.loads(args.fragments.read_text(encoding="utf-8-sig"))
        prompt = render_merge_prompt(bundle, fragments)
        if args.render:
            print(prompt, end="")
            return 0
        from hf_client import generate_text
        answer = generate_text(prompt, args.model, device=args.device, max_new_tokens=192).strip()
        fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", answer, re.DOTALL | re.IGNORECASE)
        try:
            proposal = json.loads(fence.group(1) if fence else answer)
        except ValueError as error:
            print(json.dumps({"status": "invalid_input", "error": str(error), "raw_reply": answer}, indent=2))
            return 2
        report = check_merge(bundle, fragments, proposal)
        report["proposal"] = proposal
        print(json.dumps(report, indent=2))
        return {"passed": 0, "failed": 1, "conflict": 1, "invalid_input": 2}[report["status"]]
    if args.operation == "render":
        print(render_chat_prompt(bundle) if args.input_format == "chat" else render_prompt(bundle), end="")
        return 0
    if args.operation == "generate":
        report = generate_plan(bundle, args.model, device=args.device,
                               max_new_tokens=args.max_new_tokens, input_format=args.input_format)
        if args.save_program:
            args.save_program.parent.mkdir(parents=True, exist_ok=True)
            args.save_program.write_text(report["program"], encoding="utf-8")
    else:
        program = args.program.read_text(encoding="utf-8-sig")
        report = check_program(program, bundle)
        report.update(source="saved_program", program=program)
    print(json.dumps(report, indent=2))
    return {"passed": 0, "failed": 1, "invalid_program": 2}[report["status"]]
