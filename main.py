"""Verify symbolic actions, run local Hugging Face inference, or fine-tune a model."""

import argparse
import json
import sys
from pathlib import Path

from verifier.tabletop import verify_task


DEFAULT_TASK = Path(__file__).resolve().parent / "tasks" / "cup_to_tray.json"


def run_verifier(path):
    try:
        with path.open(encoding="utf-8-sig") as task_file:
            bundle = json.load(task_file)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}), file=sys.stderr)
        return 2
    report = verify_task(bundle)
    print(json.dumps(report, indent=2))
    return {"passed": 0, "failed": 1, "invalid_input": 2}[report["status"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    verifier = commands.add_parser("verify", help="Check a recorded tabletop task (default).")
    verifier.add_argument("--task", type=Path, default=DEFAULT_TASK, help="Path to the task JSON.")
    from hf_client import add_arguments as add_inference_arguments, run_inference
    add_inference_arguments(commands.add_parser("infer", help="Query local Hugging Face model weights."))
    from finetuning.train import add_arguments, run_training
    add_arguments(commands.add_parser("finetune", help="Train on the bundled household instruction/step pairs."))
    args = parser.parse_args()
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
    return run_verifier(args.task if args.command == "verify" else DEFAULT_TASK)


if __name__ == "__main__":
    raise SystemExit(main())
