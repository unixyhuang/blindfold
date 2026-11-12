"""End-to-end contracts for the three published ordinary symbolic transfers."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import main
from progprompt.feedback import expected_feedback
from progprompt.workflow import optimize_plan
from verifier.tabletop import verify_task


ROOT = Path(__file__).resolve().parents[1]
TASK_NAMES = ("cup_to_tray", "cup_to_counter", "apple_to_counter")


def task(name):
    return json.loads((ROOT / "tasks" / f"{name}.json").read_text(encoding="utf-8"))


def primitives(bundle):
    item, destination = bundle["goal"]["on"]
    return ({"action": "inspect", "object": item}, {"action": "pick", "object": item},
            {"action": "place", "object": item, "target": destination})


class TransferWorkflowTests(unittest.TestCase):
    def test_verified_program_reaches_identical_final_state_with_fewer_actions(self):
        for name in TASK_NAMES:
            with self.subTest(task=name):
                bundle = task(name)
                item, destination = bundle["goal"]["on"]
                program = ("def plan():\n" + f'    inspect("{item}")\n' * 12
                           + f'    pick("{item}")\n    place("{item}", "{destination}")\n'
                           + '    assert hand_empty()\n')
                source = {"program": program}
                flow = optimize_plan(bundle, source)
                self.assertEqual(flow["status"], "ready")
                self.assertEqual(flow["initial_plan"], source)
                self.assertEqual(flow["repairs_used"], 0)
                self.assertEqual(len(flow["source_verifier"]["actions"]), 14)
                self.assertTrue(flow["source_verifier"]["assertions"][-1]["value"])
                self.assertEqual(flow["final_plan"]["actions"], list(primitives(bundle)[1:]))
                self.assertEqual(flow["source_verifier"]["final_state"], flow["final_plan"]["final_state"])

    def test_repair_uses_whole_linear_program_and_preserves_original_diagnostics(self):
        bundle = task("cup_to_counter")
        inspect, pick, place = primitives(bundle)
        program = 'def plan():\n    place("cup_1", "counter_1")\n    pick("cup_1")\n    inspect("cup_1")\n'
        # A misleading source verdict and reference trace cannot substitute for actual verification.
        bundle["actions"] = [{"action": "reference_must_not_be_used"}]
        source = {"status": "passed", "goal_met": True, "program": program, "actions": [pick, place]}
        original = deepcopy((source, bundle))
        flow = optimize_plan(bundle, source, max_repairs=1)
        self.assertEqual(flow["status"], "ready")
        self.assertEqual((source, bundle), original)
        self.assertEqual(flow["initial_plan"], source)
        self.assertEqual(flow["source_verifier"]["actions"], [place])
        error, = flow["source_verifier"]["errors"]
        self.assertEqual((error["phase"], error["line"], error["action_index"]), ("action", 2, 0))
        self.assertEqual(flow["action_source"], "complete_static_action_only_program")
        attempt, = flow["attempts"]
        self.assertEqual(attempt["input_actions"], [place, pick, inspect])
        verifier = verify_task({**bundle, "actions": [place, pick, inspect]})
        self.assertEqual(attempt["verifier"], verifier)
        self.assertEqual(attempt["feedback"], expected_feedback(verifier))
        repaired = attempt["repair"]
        self.assertCountEqual(repaired["candidate_original_indices"], [0, 1, 2])
        self.assertIn(inspect, repaired["candidate_actions"])
        self.assertEqual(attempt["candidate_verifier"], verify_task({**bundle, "actions": repaired["candidate_actions"]}))
        self.assertEqual(flow["final_plan"]["actions"], [pick, place])

    def test_unmet_assertions_control_flow_and_invalid_program_never_reach_simulator(self):
        cases = [
            ('pick("cup_1")\n    place("cup_1", "counter_1")\n    assert holding("cup_1")',
             "failed_assertion_preserved", "assertion", 4),
            ('place("cup_1", "counter_1")\n    assert hand_empty()',
             "failed_program_requires_action_only_body", "action", 2),
            ('if not holding("cup_1"):\n        place("cup_1", "counter_1")',
             "failed_program_requires_action_only_body", "action", 3),
            ('pick("cup_1")\n    wave("cup_1")', "invalid_source_program", "parse", 3),
            ('place(', "invalid_source_program", "parse", 2),
        ]
        with tempfile.TemporaryDirectory() as directory, patch("simulators.virtualhome.UnityClient") as client:
            for number, (body, reason, phase, line) in enumerate(cases):
                with self.subTest(reason=reason, line=line):
                    folder = Path(directory) / str(number)
                    source = Path(directory) / f"source-{number}.py"
                    source.write_text("def plan():\n    " + body + "\n", encoding="utf-8")
                    argv = ["main.py", "virtualhome", "run", "--backend", "unity", "--optimize",
                            "--task", "cup_to_counter", "--program", str(source), "--output-dir", str(folder)]
                    with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                        self.assertNotEqual(main.main(), 0)
                    client.assert_not_called()
                    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["execution"], [])
                    flow = report["workflow"]
                    self.assertIsNone(flow["final_plan"])
                    self.assertEqual(flow["attempts"], [])
                    self.assertEqual(flow["termination"], reason)
                    self.assertEqual((folder / "original-plan.py").read_text(encoding="utf-8"),
                                     source.read_text(encoding="utf-8"))
                    first = flow["source_verifier"]["errors"][0]
                    self.assertEqual((first["phase"], first["line"]), (phase, line))

    def test_explicit_action_failures_and_repair_limits(self):
        bundle = task("cup_to_tray")
        _, pick, place = primitives(bundle)
        forged = {"actions": [place], "status": "passed", "goal_met": True}
        no_budget = optimize_plan(bundle, forged, max_repairs=0)
        self.assertEqual(no_budget["termination"], "repair_limit")
        self.assertEqual(no_budget["source_verifier"]["errors"][0]["rule_id"], "item_not_held")
        self.assertEqual(no_budget["repairs_used"], 0)
        self.assertIsNone(no_budget["final_plan"])
        one = optimize_plan(bundle, forged, max_repairs=1)
        self.assertEqual(one["repairs_used"], 1)
        self.assertEqual(one["final_plan"]["actions"], [pick, place])
        for invalid in (-1, 4, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                optimize_plan(bundle, forged, max_repairs=invalid)
        unknown = optimize_plan(bundle, {"status": "passed", "actions": [{"action": "wave", "object": "cup_1"}]})
        self.assertEqual(unknown["termination"], "invalid_task_or_actions")
        self.assertIsNone(unknown["final_plan"])

    def test_invalid_initial_scene_does_not_trigger_static_extraction_of_unparsed_program(self):
        bundle = task("cup_to_tray")
        bundle["scene"]["cup"]["empty"] = False
        result = optimize_plan(bundle, {"program": "def plan(:"})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["attempts"], [])
        self.assertIsNone(result["final_plan"])

    def test_unchanged_candidate_is_rechecked_and_loop_terminates(self):
        bundle = task("apple_to_counter")
        actions = [primitives(bundle)[2]]
        dishonest = {"status": "repaired", "candidate_actions": deepcopy(actions),
                     "verifier": {"status": "passed", "goal_met": True}}
        with patch("progprompt.workflow.repair_actions", return_value=dishonest) as propose:
            flow = optimize_plan(bundle, {"actions": actions}, max_repairs=3)
        propose.assert_called_once()
        self.assertEqual(flow["termination"], "no_progress")
        self.assertIsNone(flow["final_plan"])
        attempt, = flow["attempts"]
        self.assertEqual(attempt["candidate_verifier"], verify_task({**bundle, "actions": actions}))
        self.assertFalse(attempt["candidate_verifier"]["goal_met"])

    def test_cli_failed_assertion_never_reaches_backend_or_exports_a_selected_plan(self):
        program = 'def plan():\n    pick("cup_1")\n    place("cup_1", "counter_1")\n    assert holding("cup_1")\n'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.py"
            source.write_text(program, encoding="utf-8")
            folder = Path(directory) / "run"
            run = subprocess.run([sys.executable, "-B", "-S", "main.py", "virtualhome", "run",
                                  "--backend", "unity", "--task", "cup_to_counter", "--program", str(source),
                                  "--optimize", "--output-dir", str(folder)], cwd=ROOT,
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 2, run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report["status"], "workflow_failed")
            self.assertEqual(report["workflow"]["termination"], "failed_assertion_preserved")
            self.assertEqual(report["execution"], [])
            self.assertEqual((folder / "original-plan.py").read_text(encoding="utf-8"), program)
            self.assertFalse((folder / "plan.py").exists())
            self.assertFalse((folder / "before_graph.json").exists())

    def test_cli_repairs_and_runs_three_transfers_on_evolving_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in TASK_NAMES:
                with self.subTest(task=name):
                    bundle = task(name)
                    _, pick, place = primitives(bundle)
                    source = Path(directory) / f"{name}.json"
                    source.write_text(json.dumps([place]), encoding="utf-8")
                    folder = Path(directory) / name
                    result = subprocess.run([sys.executable, "-B", "-S", "main.py", "virtualhome", "run",
                                             "--backend", "evolving-graph", "--task", name, "--actions", str(source),
                                             "--optimize", "--max-repairs", "1", "--output-dir", str(folder)],
                                            cwd=ROOT, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, (result.stderr, result.stdout))
                    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["backend"], "virtualhome_evolving_graph")
                    self.assertEqual(report["status"], "passed")
                    flow = json.loads((folder / "workflow.json").read_text(encoding="utf-8"))
                    self.assertEqual(flow, report["workflow"])
                    self.assertEqual(flow["initial_plan"]["actions"], [place])
                    self.assertEqual(flow["repairs_used"], 1)
                    self.assertEqual(flow["final_plan"]["actions"], [pick, place])
                    item, dest = [report["bindings"][s] for s in bundle["goal"]["on"]]
                    edges = json.loads((folder / "after_graph.json").read_text(encoding="utf-8"))["edges"]
                    self.assertTrue(any(e["from_id"] == item and e["to_id"] == dest and e["relation_type"] == "ON"
                                        for e in edges))
                    self.assertFalse(any(e["from_id"] == report["character_id"] and
                                         e["relation_type"] in {"HOLDS_RH", "HOLDS_LH"} for e in edges))


if __name__ == "__main__":
    unittest.main()
