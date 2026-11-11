"""Run symbolic action verification or query the local Ollama service."""

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
    ollama = commands.add_parser("ollama", help="Query a local Ollama model.")
    ollama.add_argument("--model", default="llama3.1", help="Installed Ollama model tag.")
    from finetuning.train import add_arguments, run_training
    add_arguments(commands.add_parser("finetune", help="Train on the bundled household instruction/step pairs."))
    args = parser.parse_args()
    if args.command == "finetune":
        try:
            return run_training(args)
        except (ValueError, OSError, RuntimeError) as error:
            print(f"Fine-tuning stopped: {error}", file=sys.stderr)
            return 2
    if args.command == "ollama":
        from ollama_client import main as query_model
        return query_model(args.model)
    return run_verifier(args.task if args.command == "verify" else DEFAULT_TASK)


if __name__ == "__main__":
    raise SystemExit(main())
