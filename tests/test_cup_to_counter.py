import json
import unittest
from copy import deepcopy
from pathlib import Path

from progprompt.runtime import check_program
from verifier.tabletop import verify_task


TASKS = Path(__file__).resolve().parents[1] / "tasks"
BUNDLE = json.loads((TASKS / "cup_to_counter.json").read_text(encoding="utf-8"))


class CupToCounterTests(unittest.TestCase):
    def test_recorded_and_program_transfers_reach_the_counter_with_empty_gripper(self):
        code = """def plan():
    assert on("cup_1", "table_1")
    pick("cup_1")
    place("cup_1", "counter_1")
    assert on("cup_1", "counter_1")
    assert hand_empty()
"""
        for report in (verify_task(BUNDLE), check_program(code, {**BUNDLE, "actions": []})):
            self.assertTrue(report["goal_met"], report["errors"])
            self.assertEqual(report["final_state"]["cup"]["on"], "counter_1")
            self.assertIsNone(report["final_state"]["arm"]["held"])

    def test_cup_conditions_and_counter_availability_are_enforced(self):
        for entity, key, value, rule in (
            ("cup", "empty", False, "cup_condition"),
            ("cup", "temperature", "hot", "item_temperature"),
            ("cup", "on", "counter_1", "initial_support"),
            ("counter", "occupied", True, "destination_occupied"),
        ):
            with self.subTest(rule=rule):
                bundle = deepcopy(BUNDLE)
                bundle["scene"][entity][key] = value
                report = verify_task(bundle)
                self.assertEqual(report["errors"][0]["rule_id"], rule)
                self.assertFalse(report["goal_met"])

    def test_counter_and_tray_goals_cannot_be_interchanged(self):
        tray = json.loads((TASKS / "cup_to_tray.json").read_text(encoding="utf-8"))
        for bundle, wrong_goal in ((BUNDLE, tray["goal"]), (tray, BUNDLE["goal"])):
            with self.subTest(task=bundle["task_id"]):
                report = verify_task({**bundle, "goal": wrong_goal})
                self.assertEqual(report["status"], "invalid_input")
                self.assertFalse(report["goal_met"])


if __name__ == "__main__":
    unittest.main()
