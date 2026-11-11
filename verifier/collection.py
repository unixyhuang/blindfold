"""Select local SafeAgentBench records and report symbolic and observed evidence."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from verifier.observations import evaluate_snapshot
from verifier.safeagentbench import verify_record


COLLECTION = Path(__file__).resolve().parents[1] / "tasks" / "safeagentbench"


def read_json(path):
    with path.open(encoding="utf-8-sig") as source:
        return json.load(source)


def load_collection():
    manifest = read_json(COLLECTION / "selection.json")
    body = (COLLECTION / "tasks.jsonl").read_bytes()
    if not isinstance(manifest, dict) or hashlib.sha256(body).hexdigest() != manifest.get("records_sha256"):
        raise ValueError("The SafeAgentBench collection checksum does not match selection.json.")
    records = [json.loads(line) for line in body.decode("utf-8").splitlines()]
    if len(records) != 100 or manifest.get("records") != len(records):
        raise ValueError("The bundled SafeAgentBench collection must contain 100 records.")
    if any(not isinstance(row, dict) for row in records):
        raise ValueError("Each SafeAgentBench record must be a JSON object.")
    rows = [row.get("source_row") for row in records]
    if rows != manifest.get("source_rows"):
        raise ValueError("Source rows do not match the SafeAgentBench selection manifest.")
    return records


def assess_record(record, metadata_path=None):
    report = verify_record(record)
    if metadata_path is not None and report["status"] != "invalid_input":
        report["observed_goal"] = evaluate_snapshot(record, read_json(metadata_path))
    return report


def verify_collection(task_id=None, scene=None, metadata_path=None):
    if metadata_path is not None and task_id is None:
        raise ValueError("--metadata requires --task-id when verifying a benchmark.")
    records = load_collection()
    if task_id is not None:
        for record in records:
            if task_id == record.get("task_id"):
                return assess_record(record, metadata_path)
        raise ValueError(f"No SafeAgentBench record matches task ID {task_id!r}.")
    if scene is not None:
        records = [row for row in records if row.get("scene_name") == scene]
        if not records:
            raise ValueError(f"No SafeAgentBench record matches scene {scene!r}.")
    reports = [assess_record(record) for record in records]
    return {
        "benchmark": "safeagentbench",
        "summary": {
            "tasks": len(reports),
            "scenes": len({row["scene_name"] for row in records}),
            "status_counts": dict(sorted(Counter(r["status"] for r in reports).items())),
            "trace_status_counts": dict(sorted(Counter(r["trace_status"] for r in reports).items())),
            "goal_status_counts": dict(sorted(Counter(r["goal_status"] for r in reports).items())),
        },
        "results": reports,
    }


def exit_code(report):
    reports = report.get("results", [report])
    statuses = {r["status"] for r in reports}
    statuses.update(r["observed_goal"]["status"] for r in reports if "observed_goal" in r)
    if "invalid_input" in statuses:
        return 2
    return int(bool(statuses & {"failed", "contradicted"}))
