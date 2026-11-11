"""Run the public tabletop verifier or the standalone local Ollama example."""

import argparse
import json
import sys
from pathlib import Path

from demo.tabletop import verify_task


DEFAULT_TASK = Path(__file__).resolve().parent / "assets" / "examples" / "task_bundle.json"


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
    commands.add_parser("ollama", help="Send a sample chat message to local llama3.1.")
    args = parser.parse_args()
    if args.command == "ollama":
        from examples.ollama_local import main as ollama_example
        return ollama_example()
    return run_verifier(args.task if args.command == "verify" else DEFAULT_TASK)


if __name__ == "__main__":
    raise SystemExit(main())
