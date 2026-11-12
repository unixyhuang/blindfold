"""Generate and check plans for the pinned ordinary SafeAgentBench collection."""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from string import Template

from progprompt.benchmark_report import write_reports
from progprompt.inventory import missing_mentions
from verifier.collection import COLLECTION, load_collection
from verifier.safeagentbench import OBJECT_TYPES


TEMPLATE = Path(__file__).resolve().parents[1] / "prompts/progprompt/domain_action_generation.txt"
PUBLISHED_RUN = Path(__file__).resolve().parents[1] / "results/llama31-safeagentbench-100"


def render_instruction(instruction, scene, objects, template):
    return template.substitute(scene=json.dumps(scene), objects=json.dumps(sorted(objects)),
                               instruction=instruction).strip()


def extract_program(answer):
    """Take one clearly delimited program, keeping all raw responses on disk."""
    text = answer.strip()
    if "```" not in text:
        return text + "\n", "plain"
    block = re.search(r"^```(?:python)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*$",
                      text, flags=re.DOTALL | re.MULTILINE | re.IGNORECASE)
    if text.count("```") == 2 and block:
        outside = (text[:block.start()] + "\n" + text[block.end():]).strip()
        if not re.search(r"^\s*(?:def\s|class\s|import\s|from\s+\w+\s+import\s|\w+\s*\()", outside, re.MULTILINE):
            return block.group(1) + "\n", "single_block_with_prose" if outside else "single_block"
    return text + "\n", "invalid_envelope"


def reasons(report):
    """Describe the failed/unknown checks on the generated trace only."""
    status = report["status"]
    if status == "supported":
        return []
    details = []
    for issue in report.get("issues", []):
        code = issue.get("rule", "verification_issue")
        if code != "liquid_outcome_unobserved":
            detail = {"code": code, "message": issue.get("message") or str(issue)}
            if issue.get("line") is not None:
                detail["line"] = issue["line"]
            details.append(detail)
    return details or [{"code": status, "message": f"No supported terminal goal ({status})."}]


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path, value):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pending.replace(path)


def summarize(results):
    return {
        "tasks": len(results),
        "scenes": len({r["scene_name"] for r in results}),
        "status_counts": dict(sorted(Counter(r["status"] for r in results).items())),
        "trace_status_counts": dict(sorted(Counter(r["trace_status"] for r in results).items())),
        "response_format_counts": dict(sorted(Counter(r["response_format"] for r in results).items())),
        "status_if_surrounding_prose_rejected": dict(sorted(Counter(
            "invalid_program" if r["response_format"] == "single_block_with_prose" else r["status"]
            for r in results).items())),
        "tasks_with_inventory_gaps": sum(bool(r["inventory_missing_mentions"]) for r in results),
        "reason_task_counts": dict(Counter(reason for r in results
                                            for reason in {f["code"] for f in r["reasons"]}).most_common()),
    }


def add_arguments(parser):
    parser.add_argument("--model", required=True, type=Path, help="Local Hugging Face checkpoint directory.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for this run and its reports.")
    parser.add_argument("--inventories", type=Path, default=COLLECTION / "scene_objects.json")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--device", choices=["auto", "cpu"], default="auto")
    parser.add_argument("--task-id", help="Optional exact ID for a single-record run.")


def prepare_jobs(inventory_path, task_id=None):
    records = load_collection()
    if task_id:
        records = [r for r in records if r["task_id"] == task_id]
        if not records:
            raise ValueError("Unknown benchmark task ID.")
    catalog = json.loads(inventory_path.read_text(encoding="utf-8"))
    template = Template(TEMPLATE.read_text(encoding="utf-8"))
    jobs = []
    for record in records:
        scene = record["scene_name"]
        room = catalog["inventories"].get(scene)
        if not isinstance(room, list) or not all(isinstance(item, str) for item in room):
            raise ValueError(f"Missing or invalid object inventory for {scene}.")
        objects = sorted(OBJECT_TYPES & {"".join(item.casefold().split()) for item in room})
        if not objects:
            raise ValueError(f"No supported object types for {scene}.")
        jobs.append((record, objects, render_instruction(record["instruction"], scene, objects, template)))

    inputs = {"goals": "reviewed", "inventory_source": catalog["source"],
              "inventory_sha256": digest(inventory_path), "dataset_sha256": digest(COLLECTION / "tasks.jsonl"),
              "goal_annotations_sha256": digest(COLLECTION / "goal_annotations.json"),
              "prompt_sha256": {r["task_id"]: hashlib.sha256(p.encode()).hexdigest() for r, _, p in jobs}}
    return jobs, inputs


def run(args):
    from hf_client import LocalGenerator

    if args.batch_size < 1 or args.max_new_tokens < 1:
        raise ValueError("Batch size and token limit must be positive.")
    jobs, inputs = prepare_jobs(args.inventories, args.task_id)
    if not args.model.is_dir():
        raise ValueError("--model must be a local Hugging Face checkpoint directory.")
    weights = sorted(args.model.glob("*.safetensors"))
    if not weights:
        raise ValueError("Expected local Safetensors weights in --model.")
    model_files = weights + [p for p in sorted(args.model.iterdir()) if p.is_file() and
                             p.suffix in {".json", ".jinja", ".model", ".txt"}]
    manifest = {"model": args.model.name, "model_files_sha256": {p.name: digest(p) for p in model_files},
                "device": args.device, "batch_size": args.batch_size, "max_new_tokens": args.max_new_tokens,
                "decoding": "greedy", "input_format": "chat", **inputs}
    folder = args.output_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    answers_path = folder / "completions.json"
    if answers_path.exists() and not path.exists():
        raise ValueError("Existing completions have no run manifest. Choose a new output directory.")
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Output directory belongs to a different run. Choose another directory.")
    write_json(path, manifest)
    # Persist completed batches so an interrupted run can resume without regenerating plans.
    answers = json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.exists() else {}
    if (not isinstance(answers, dict) or set(answers) - set(manifest["prompt_sha256"])
            or any(not isinstance(answer, str) for answer in answers.values())):
        raise ValueError("Saved completions must map IDs from this run to raw model responses.")
    pending = [job for job in jobs if job[0]["task_id"] not in answers]
    if pending:
        generator = LocalGenerator(args.model, device=args.device)
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start:start + args.batch_size]
            raw = generator.generate_many([p for _, _, p in batch], max_new_tokens=args.max_new_tokens)
            for (record, _, _), answer in zip(batch, raw, strict=True):
                answers[record["task_id"]] = answer
            write_json(answers_path, answers)
            print(f"Generated {len(answers)}/{len(jobs)} plans", file=sys.stderr, flush=True)
    return score_batch(jobs, answers, folder)


def replay_published(folder):
    """Rebuild the reports for the complete published batch with the standard library."""
    if folder.resolve().is_relative_to(PUBLISHED_RUN.resolve()):
        raise ValueError("Choose an output directory outside the published run.")
    jobs, inputs = prepare_jobs(COLLECTION / "scene_objects.json")
    manifest = json.loads((PUBLISHED_RUN / "manifest.json").read_text(encoding="utf-8"))
    for field, expected in inputs.items():
        if manifest.get(field) != expected:
            raise ValueError(f"Published run does not match the current inputs: {field}.")
    answers = json.loads((PUBLISHED_RUN / "completions.json").read_text(encoding="utf-8"))
    if (not isinstance(answers, dict) or set(answers) != set(inputs["prompt_sha256"])
            or any(not isinstance(answer, str) for answer in answers.values())):
        raise ValueError("Expected one raw response for every published task ID.")
    if (folder / "manifest.json").exists() and json.loads(
            (folder / "manifest.json").read_text(encoding="utf-8")) != manifest:
        raise ValueError("The output directory belongs to another generation run.")
    folder.mkdir(parents=True, exist_ok=True)
    return score_batch(jobs, answers, folder)


def score_batch(jobs, answers, folder):
    from progprompt.benchmark_runtime import check_benchmark_program

    results = []
    for record, objects, prompt in jobs:
        answer = answers[record["task_id"]]
        program, response_format = extract_program(answer)
        result = check_benchmark_program(program, record, objects)
        result.update(task_id=record["task_id"], scene_name=record["scene_name"],
                      instruction=record["instruction"], goal_origin=record["goal_origin"],
                      expected_goal=record["final_state"], prompt=prompt, program=program,
                      response_format=response_format, inventory_missing_mentions=missing_mentions(
                          record["instruction"], objects))
        result["reasons"] = reasons(result)
        results.append(result)
    write_json(folder / "results.json", results)
    summary = summarize(results)
    write_json(folder / "summary.json", summary)
    failures = [{k: r[k] for k in ("task_id", "scene_name", "instruction", "status", "reasons",
                                    "inventory_missing_mentions")}
                for r in results if r["status"] != "supported"]
    write_json(folder / "not-supported.json", failures)
    write_reports(folder, results, summary)
    print(json.dumps(summary, indent=2))
    return 0
