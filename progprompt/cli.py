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
TASKS = {"cup_to_tray": "cup_to_tray.json", "apple_to_counter": "apple_to_counter.json"}


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


def add_arguments(parser):
    commands = parser.add_subparsers(dest="operation", required=True)
    render = commands.add_parser("render", help="Print the exact prompt sent to the model.")
    generate = commands.add_parser("generate", help="Generate a program locally and check it.")
    replay = commands.add_parser("replay", help="Check a saved program on its symbolic scene.")
    fuse = commands.add_parser("fuse", help="Reconcile two fragments of one tabletop transfer.")
    fuse.add_argument("--fragments", type=Path, required=True, help="JSON array containing two event lists.")
    mode = fuse.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true", help="Print the populated reconciliation prompt.")
    mode.add_argument("--model", type=Path, help="Propose an event order with a local Hugging Face checkpoint.")
    fuse.add_argument("--device", choices=["auto", "cpu"], default="auto")
    from progprompt import benchmark
    benchmark.add_arguments(commands.add_parser("benchmark", help="Generate and verify SafeAgentBench plans."))
    for command in (render, generate, replay, fuse):
        command.add_argument("--task", choices=sorted(TASKS), default="cup_to_tray")
    generate.add_argument("--model", type=Path, required=True, help="Local Hugging Face checkpoint.")
    generate.add_argument("--device", choices=["auto", "cpu"], default="auto")
    generate.add_argument("--max-new-tokens", type=int, default=256)
    generate.add_argument("--save-program", type=Path, help="Save the program text for replay.")
    replay.add_argument("--program", required=True, type=Path, help="Path to a plan containing def plan().")


def run(args):
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
        print(render_prompt(bundle), end="")
        return 0
    if args.operation == "generate":
        from hf_client import generate_text
        prompt = render_prompt(bundle)
        response = generate_text(prompt, args.model, device=args.device,
                                 max_new_tokens=args.max_new_tokens, completion=True)
        program = as_program(response)
        if args.save_program:
            args.save_program.parent.mkdir(parents=True, exist_ok=True)
            args.save_program.write_text(program, encoding="utf-8")
    else:
        program = args.program.read_text(encoding="utf-8-sig")
    report = check_program(program, bundle)
    report["source"] = "model_generated" if args.operation == "generate" else "saved_program"
    report["program"] = program
    if args.operation == "generate":
        report["raw_completion"] = response
        report["generation"] = {"model_directory": str(args.model), "max_new_tokens": args.max_new_tokens,
                                "decoding": "greedy", "input_format": "causal_completion",
                                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
    print(json.dumps(report, indent=2))
    return {"passed": 0, "failed": 1, "invalid_program": 2}[report["status"]]
