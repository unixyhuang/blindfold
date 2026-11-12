import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from progprompt.feedback import expected_feedback, render_feedback, run
from progprompt.runtime import check_program
from progprompt.tabletop_merge import check_merge
from verifier.tabletop import verify_task


ROOT = Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    def test_default_feedback_needs_no_model_and_preserves_unknown(self):
        report = {"task_id": "sab-safe-test", "status": "unknown", "index_base": 0,
                  "issues": [{"rule": "unobserved_liquid_transfer", "message": "No observation."}],
                  "checks": []}
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            record = Path(directory) / "report.json"
            record.write_text(json.dumps(report), encoding="utf-8")
            args = Namespace(record=record, render=False, model=None, device="cpu")
            out = io.StringIO()
            with patch("hf_client.generate_text", side_effect=AssertionError("Model should not load")), redirect_stdout(out):
                self.assertEqual(run(args), 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["status"], "feedback_ready")
            self.assertEqual(result["feedback"], expected_feedback(report))

    def setUp(self):
        self.task = json.loads((ROOT / "tasks/cup_to_tray.json").read_text(encoding="utf-8"))

    def test_tabletop_goal_nulls_are_preserved(self):
        record = verify_task({**self.task, "actions": []})
        before = deepcopy(record)
        result = expected_feedback(record)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["diagnostics"]["errors"], record["errors"])
        self.assertIsNone(result["diagnostics"]["errors"][0]["action_index"])
        self.assertIsNone(result["diagnostics"]["errors"][0]["action_name"])
        self.assertEqual(record, before)

    def test_program_parse_and_assertion_locations(self):
        for source in ("def plan():\n    print('hi')", "def plan():\n    assert holding('cup_1')"):
            record = check_program(source, self.task)
            feedback = expected_feedback(record)
            self.assertEqual(feedback["diagnostics"]["errors"], record["errors"])
            self.assertNotIn("action_index", feedback["diagnostics"]["errors"][0])
            self.assertIn("line", feedback["diagnostics"]["errors"][0])

    def test_unknown_and_observed_goal_remain_distinct(self):
        report = {"task_id": "sab-safe-test", "status": "unknown", "index_base": 0,
                  "issues": [{"rule": "unobserved_liquid_transfer", "message": "No observation."}],
                  "checks": [{"objectType": "Mug", "predicate": "liquidType", "expected": "water", "status": "unknown"}],
                  "assertions": [], "observed_goal": {"status": "contradicted", "checks": []}}
        output = expected_feedback(report)
        self.assertEqual(output["status"], "unknown")
        self.assertEqual(output["diagnostics"]["observed_goal"], report["observed_goal"])
        self.assertEqual(output["diagnostics"]["issues"], report["issues"])

    def test_fusion_coverage_and_unverified_conflict(self):
        fragments = json.loads((ROOT / "tasks/progprompt/cup_fragments.json").read_text())
        record = check_merge(self.task, fragments, {"status": "merged", "order": ["grasp", "release"]})
        result = expected_feedback(record)
        self.assertIsNone(result["diagnostics"]["verifier"])
        self.assertEqual(result["diagnostics"]["errors"][0]["missing"], ["look"])
        conflict = check_merge(self.task, fragments, {"status": "conflict", "reason": "Unresolved."})
        output = expected_feedback(conflict)
        self.assertEqual(output["status"], "conflict")
        self.assertEqual(output["diagnostics"]["reason"], "Unresolved.")
        self.assertIsNone(output["diagnostics"]["verifier"])

    def test_success_and_complete_nested_verifier(self):
        fragments = json.loads((ROOT / "tasks/progprompt/cup_fragments.json").read_text())
        record = check_merge(self.task, fragments, {"status": "merged", "order": ["look", "grasp", "release"]})
        result = expected_feedback(record)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["diagnostics"]["errors"], [])
        self.assertEqual(result["diagnostics"]["verifier"], record["verifier"])
        changed = deepcopy(record)
        changed["verifier"]["task_id"] = "different"
        changed["verifier"]["run_id"] = "different"
        with self.assertRaises(ValueError):
            expected_feedback(changed)

    def test_invalid_source_fields(self):
        record = verify_task(self.task)
        cases = [{**record, "status": "invented"}, {**record, "status": []}, {**record, "run_id": "another"},
                 {**record, "index_base": True}, {**record, "errors": "none"},
                 {**record, "goal_met": 1}, {**record, "checks": float("nan")},
                 {"status": "failed", "task_id": "one"},
                 {**record, "issues": [{}]}, {**record, "assertions": [{"line": True}]}]
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                expected_feedback(bad)

    def test_cli_json_matching_and_typed_mismatch(self):
        report = verify_task({**self.task, "actions": []})
        expected = expected_feedback(report)
        wrong = deepcopy(expected)
        wrong["diagnostics"]["index_base"] = False
        replies = [(json.dumps(expected), 0), ("```json\n" + json.dumps(expected) + "\n```", 0),
                   (json.dumps(wrong), 2), ('{"status":"passed"}', 2), ('{"task_id":1,"task_id":2}', 2)]
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            args = Namespace(record=path, render=False, model=Path("weights"), device="cpu")
            for reply, exit_code in replies:
                with self.subTest(reply=reply), patch("hf_client.generate_text", return_value=reply), redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(run(args), exit_code)
                    data = json.loads(out.getvalue())
                    self.assertEqual(data["status"], "feedback_verified" if exit_code == 0 else "feedback_mismatch")
            args.render = True
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(run(args), 0)
            self.assertEqual(out.getvalue().rstrip("\n"), render_feedback(report).rstrip("\n"))
            path.write_text('{"task_id":"a","task_id":"b"}', encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(run(args), 2)
            self.assertEqual(json.loads(out.getvalue())["status"], "invalid_input")
