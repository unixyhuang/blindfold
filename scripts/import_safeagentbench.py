"""Rebuild the curated 100-task SafeAgentBench collection from a pinned source."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REVISION = "52c8da9b57edbd2f5a7c39e9ab22f28f6d6b58df"
SOURCE_URL = f"https://huggingface.co/datasets/safeagentbench/SafeAgentBench/resolve/{REVISION}/safe_detailed.jsonl"
SOURCE_SHA256 = "6d86acf164ff1caece3dcc145ab34ad248896e5d1fe2fe353b0fad18c0560e40"
SEED = "safeagentbench-100-v1"
COUNT = 100
FIELDS = ("instruction", "scene_name", "step", "final_state")
EXCLUDED_TERMS = r"\b(?:microwave|stoveburner|stoveknob|toaster|slice|drop|throw|break|tripping|thief)\b"
EXCLUDED_ACTIVATION = r"\bturn(?:_| )on\s+(?:the\s+)?(?:candle|coffeemachine)"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def rank(item):
    return digest(f"{SEED}:{item[0]}".encode())


def band(row):
    steps = len(row["step"])
    return "short" if steps <= 3 else "medium" if steps <= 5 else "long"


def select(rows):
    candidates = []
    for number, row in enumerate(rows, 1):
        text = row["instruction"] + " " + " ".join(row["step"])
        if re.search(EXCLUDED_TERMS, text, re.IGNORECASE):
            continue
        if re.search(EXCLUDED_ACTIVATION, text, re.IGNORECASE):
            continue
        candidates.append((number, row))

    scenes = defaultdict(list)
    for item in candidates:
        scenes[item[1]["scene_name"]].append(item)
    selected = []
    instructions = set()

    def add(item):
        selected.append(item)
        instructions.add(item[1]["instruction"].strip().casefold())

    for scene in sorted(scenes):
        for item in sorted(scenes[scene], key=rank):
            if item[1]["instruction"].strip().casefold() not in instructions:
                add(item)
                break
    if len(selected) > COUNT:
        raise ValueError("Scene coverage exceeds the configured collection size.")

    targets = {"short": 9, "medium": 68, "long": 23}
    while len(selected) < COUNT:
        counts = Counter(band(row) for _, row in selected)
        scene_counts = Counter(row["scene_name"] for _, row in selected)
        available = [item for item in candidates if item[1]["instruction"].strip().casefold() not in instructions]
        if not available:
            raise ValueError("Insufficient unique task instructions.")
        item = min(available, key=lambda value: (
            -(targets[band(value[1])] - counts[band(value[1])]),
            scene_counts[value[1]["scene_name"]], rank(value)))
        add(item)
    return sorted(selected), candidates, targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, help="Use a local copy of the pinned source.")
    args = parser.parse_args()
    if args.source_file:
        body = args.source_file.read_bytes()
    else:
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "BlindfoldArtifactData"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    if digest(body) != SOURCE_SHA256:
        raise ValueError("Source checksum differs from the pinned dataset revision.")
    rows = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    selected, candidates, targets = select(rows)
    records = [{"task_id": f"sab-safe-{number:04d}", "source_row": number,
                **{key: row[key] for key in FIELDS}} for number, row in selected]
    serialized = ("\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n").encode("utf-8")
    manifest = {
        "dataset": "SafeAgentBench", "source_split": "safe_detailed",
        "source_revision": REVISION, "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256, "source_records": len(rows),
        "license": "CC-BY-4.0", "seed": SEED,
        "license_card_url": f"https://huggingface.co/datasets/safeagentbench/SafeAgentBench/blob/{REVISION}/README.md",
        "selection": {
            "description": "Curated non-heating household tasks; scene coverage followed by step-count strata, with unique case-folded instructions.",
            "excluded_terms_regex": EXCLUDED_TERMS,
            "excluded_activation_regex": EXCLUDED_ACTIVATION,
            "candidate_records": len(candidates), "candidate_scenes": len({r['scene_name'] for _, r in candidates}),
            "step_bands": {"short": "2-3", "medium": "4-5", "long": "6-10"},
            "target_step_band_counts": targets,
            "step_band_counts": dict(sorted(Counter(band(r) for r in records).items())),
            "scene_count": len({r["scene_name"] for r in records}),
            "scene_counts": dict(sorted(Counter(r["scene_name"] for r in records).items())),
        },
        "records": len(records), "records_sha256": digest(serialized),
        "source_rows": [number for number, _ in selected],
        "missing_final_state": sum(r["final_state"] is None for r in records),
        "retained_source_fields": list(FIELDS), "removed_source_fields": ["risk_instruction"],
        "added_fields": ["task_id", "source_row"],
        "annotation_policy": "Instruction, step and final_state are preserved from upstream, including missing and inconsistent annotations.",
        "annotation_notes": [
            {"source_row": number, "note": "The source instruction, steps and final-state toggle annotation may not correspond; review before scoring."}
            for number in [24] if number in {item[0] for item in selected}
        ],
    }
    output = ROOT / "tasks" / "safeagentbench"
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks.jsonl").write_bytes(serialized)
    (output / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "scenes": manifest["selection"]["scene_count"],
                      "step_bands": manifest["selection"]["step_band_counts"],
                      "missing_final_state": manifest["missing_final_state"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
