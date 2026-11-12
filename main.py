"""Verify symbolic actions, run local Hugging Face inference, or fine-tune a model."""

import argparse
import json
import sys
from pathlib import Path

from verifier.collection import assess_record, exit_code, read_json, verify_collection
from verifier.tabletop import verify_task


DEFAULT_TASK = Path(__file__).resolve().parent / "tasks" / "cup_to_tray.json"


def run_verifier(path=DEFAULT_TASK, *, benchmark=None, task_id=None, scene=None, metadata=None, goals=None):
    try:
        if benchmark == "safeagentbench":
            report = verify_collection(task_id, scene, metadata, goals or "reviewed")
        else:
            if task_id is not None or scene is not None or goals is not None:
                raise ValueError("--task-id, --scene and --goals require --benchmark safeagentbench.")
            bundle = read_json(path)
            if isinstance(bundle, dict) and "scene" not in bundle and ("step" in bundle or "scene_name" in bundle):
                report = assess_record(bundle, metadata)
            elif metadata is not None:
                raise ValueError("--metadata requires a SafeAgentBench task.")
            else:
                report = verify_task(bundle)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return exit_code(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    verifier = commands.add_parser("verify", help="Check recorded tabletop or SafeAgentBench tasks.")
    source = verifier.add_mutually_exclusive_group()
    source.add_argument("--task", type=Path, help="Path to a single task JSON object (default: cup to tray).")
    source.add_argument("--benchmark", choices=["safeagentbench"], help="Check the bundled collection.")
    select = verifier.add_mutually_exclusive_group()
    select.add_argument("--task-id", help="Select one benchmark task by its exact ID.")
    select.add_argument("--scene", help="Select all benchmark tasks for this FloorPlan name.")
    verifier.add_argument("--goals", choices=["reviewed", "upstream"],
                          help="Benchmark annotations (default: reviewed).")
    verifier.add_argument("--metadata", type=Path,
                          help="Final AI2-THOR event metadata JSON for a single SafeAgentBench task.")
    from progprompt.cli import add_arguments as add_planning_arguments, run as run_planning
    add_planning_arguments(commands.add_parser("progprompt", help="Build and replay tabletop task programs."))
    from hf_client import add_arguments as add_inference_arguments, run_inference
    add_inference_arguments(commands.add_parser("infer", help="Query local Hugging Face model weights."))
    from finetuning.train import add_arguments, run_training
    add_arguments(commands.add_parser("finetune", help="Train on the bundled household instruction/step pairs."))
    args = parser.parse_args()
    if args.command == "progprompt":
        try:
            return run_planning(args)
        except (ValueError, OSError, RuntimeError) as error:
            print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
            return 2
    if args.command == "finetune":
        try:
            return run_training(args)
        except (ValueError, OSError, RuntimeError) as error:
            print(f"Fine-tuning stopped: {error}", file=sys.stderr)
            return 2
    if args.command == "infer":
        try:
            return run_inference(args)
        except (ValueError, OSError, RuntimeError) as error:
            print(f"Inference stopped: {error}", file=sys.stderr)
            return 2
    if args.command == "verify":
        return run_verifier(args.task or DEFAULT_TASK, benchmark=args.benchmark,
                            task_id=args.task_id, scene=args.scene, metadata=args.metadata, goals=args.goals)
    return run_verifier()


if __name__ == "__main__":
    raise SystemExit(main())
