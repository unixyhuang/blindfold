import hashlib
import json
import unittest
from pathlib import Path
from string import Template

from progprompt.benchmark import TEMPLATE, extract_program, render_instruction, summarize
from progprompt.benchmark_runtime import check_benchmark_program
from verifier.collection import COLLECTION, load_collection
from verifier.safeagentbench import OBJECT_TYPES


RUN = Path(__file__).resolve().parents[1] / "results/llama31-safeagentbench-100"


class BenchmarkRunTests(unittest.TestCase):
    def test_one_program_per_response(self):
        program = "def plan():\n    find('book')"
        fenced = f"```python\n{program}\n```"
        self.assertEqual(extract_program(fenced + "\nA short explanation."),
                         (program + "\n", "single_block_with_prose"))
        for ambiguous in (fenced + "\n" + fenced, fenced + "\ndef other():\n    pass", fenced[:-3]):
            self.assertEqual(extract_program(ambiguous)[1], "invalid_envelope")

    def test_published_batch_replays_from_raw_completions(self):
        load = lambda name: json.loads((RUN / name).read_text(encoding="utf-8"))
        raw, saved, manifest = load("completions.json"), load("results.json"), load("manifest.json")
        tasks = load_collection()
        inventories = json.loads((COLLECTION / "scene_objects.json").read_text(encoding="utf-8"))["inventories"]
        template = Template(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(set(raw), {r["task_id"] for r in tasks})
        for task, row in zip(tasks, saved, strict=True):
            task_id = task["task_id"]
            self.assertEqual(row["task_id"], task_id)
            objects = OBJECT_TYPES.intersection(inventories[task["scene_name"]])
            prompt = render_instruction(task["instruction"], task["scene_name"], objects, template)
            self.assertEqual(hashlib.sha256(prompt.encode()).hexdigest(), manifest["prompt_sha256"][task_id])
            self.assertEqual(row["prompt"], prompt)
            source, framing = extract_program(raw[task_id])
            self.assertEqual((row["program"], row["response_format"]), (source, framing))
            checked = check_benchmark_program(source, {**task, "step": []}, objects)
            for key in ("status", "goal_status", "generated_steps", "issues", "checks"):
                self.assertEqual(row[key], checked[key], (task_id, key))
        self.assertEqual(summarize(saved), load("summary.json"))
        failed_ids = [r["task_id"] for r in saved if r["status"] != "supported"]
        self.assertEqual(failed_ids, [r["task_id"] for r in load("not-supported.json")])
