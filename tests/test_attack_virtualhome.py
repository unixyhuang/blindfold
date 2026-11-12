"""VirtualHome Evolving Graph execution of the verified attack chain."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from progprompt.attack import load_reference, load_task
from simulators.attack_graph import execute_attack


ROOT = Path(__file__).resolve().parents[1]
TASK = "phone_into_oven"


def fused_chain():
    reference = load_reference(TASK)
    chain = reference["command_transformer"]["chain"]
    cover = reference["cover_branch_generation"]["cover_chain"]
    index = reference["dominant_action_identification"]["index"]
    corrections = [{"action": entry["action"], "parameters": entry["parameters"]}
                   for entry in reference["chain_fusion"]["corrections"]]
    return chain[:index - 1] + cover + corrections + chain[index:]


class AttackVirtualHomeTests(unittest.TestCase):
    def test_verified_chain_executes_and_observes_the_goal(self):
        report = execute_attack(load_task(TASK), fused_chain())
        self.assertEqual(report["status"], "passed", report.get("error"))
        self.assertTrue(report["goal_met"])
        self.assertEqual(report["observed_goal"]["status"], "supported")
        checks = {check["rule"]: check["value"] for check in report["observed_goal"]["checks"]}
        self.assertEqual(checks, {"item_inside_container": True, "container_closed": True,
                                  "character_hands_empty": True})
        script = "\n".join(step["line"] for step in report["script"])
        for action in ("[find]", "[grab]", "[open]", "[putin]", "[putback]", "[close]"):
            self.assertIn(action, script)
        self.assertEqual(len(report["execution"]), len(report["script"]))
        self.assertTrue(all(step["success"] for step in report["execution"]))
        final = {node["class_name"]: node for node in report["after_graph"]["nodes"]}
        self.assertIn("CLOSED", final["oven"]["states"])
        self.assertNotIn("OPEN", final["oven"]["states"])

    def test_symbolically_invalid_chain_is_not_executed(self):
        chain = copy.deepcopy(fused_chain())
        chain = [step for step in chain if step["action"] != "close"]
        report = execute_attack(load_task(TASK), chain)
        self.assertEqual(report["status"], "invalid_plan")
        self.assertEqual(report["execution"], [])
        self.assertEqual(report["symbolic_recheck"]["errors"][0]["rule_id"], "goal_unmet")

    def test_recorded_cli_runs_virtualhome_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "attack"
            result = subprocess.run(
                [sys.executable, "-B", "-S", "main.py", "progprompt", "attack", "--task", TASK,
                 "--recorded", "--virtualhome", "--output-dir", str(folder)],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, (result.stderr, result.stdout))
            report = json.loads((folder / "attack.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ready")
            execution = json.loads((folder / "virtualhome.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["status"], "passed")
            self.assertEqual(execution["backend"], "virtualhome_evolving_graph_attack")
            self.assertTrue(execution["goal_met"])


if __name__ == "__main__":
    unittest.main()
