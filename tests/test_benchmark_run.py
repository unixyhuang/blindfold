import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from progprompt.benchmark import PUBLISHED_RUN, extract_program


class BenchmarkRunTests(unittest.TestCase):
    def test_one_program_per_response(self):
        program = "def plan():\n    find('book')"
        fenced = f"```python\n{program}\n```"
        self.assertEqual(extract_program(fenced + "\nA short explanation."),
                         (program + "\n", "single_block_with_prose"))
        for ambiguous in (fenced + "\n" + fenced, fenced + "\ndef other():\n    pass", fenced[:-3]):
            self.assertEqual(extract_program(ambiguous)[1], "invalid_envelope")

    def test_published_batch_replays_from_raw_completions(self):
        expected = json.loads((PUBLISHED_RUN / "summary.json").read_text(encoding="utf-8"))
        published_report = (PUBLISHED_RUN / "failures.md").read_text(encoding="utf-8")
        frozen = json.loads((PUBLISHED_RUN / "completions.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="replay-test-", dir=PUBLISHED_RUN.parents[1]) as tmp:
            output = Path(tmp)
            result = subprocess.run([sys.executable, "-B", "-S", "main.py", "progprompt", "replay-benchmark",
                                     "--output-dir", str(output)], cwd=PUBLISHED_RUN.parents[1],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), expected)
            self.assertEqual(json.loads((output / "summary.json").read_text(encoding="utf-8")), expected)
            self.assertEqual((output / "failures.md").read_text(encoding="utf-8"), published_report)
            rows = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 100)
            self.assertEqual({r["task_id"] for r in rows}, set(frozen))
            for row in rows:
                program, framing = extract_program(frozen[row["task_id"]])
                self.assertEqual((program, framing), (row["program"], row["response_format"]))
            failures = json.loads((output / "not-supported.json").read_text(encoding="utf-8"))
            ids = [r["task_id"] for r in failures]
            self.assertEqual(len(ids), 61)
            self.assertEqual(ids, [r["task_id"] for r in rows if r["status"] != "supported"])
            self.assertEqual(ids, re.findall(r"^\| (sab-safe-\d+) \|", published_report, re.MULTILINE))
