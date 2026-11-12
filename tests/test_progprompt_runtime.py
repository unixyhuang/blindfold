import json
import unittest
from copy import deepcopy
from pathlib import Path

from progprompt.runtime import check_program


TASKS = Path(__file__).resolve().parents[1] / "tasks"


def task(name):
    return json.loads((TASKS / f"{name}.json").read_text(encoding="utf-8"))


class TabletopProgramTests(unittest.TestCase):
    def test_plan_reads_state_before_and_after_recovery(self):
        for filename in ("cup_to_tray", "apple_to_counter"):
            with self.subTest(filename=filename):
                bundle = task(filename)
                item, target = bundle["goal"]["on"]
                bundle["actions"] = []  # No recorded solution is needed.
                original = deepcopy(bundle)
                program = f"""def plan():
    \"\"\"Transfer the object to the destination.\"\"\"
    assert on("{item}", "table_1")
    assert reachable("{target}")
    inspect("{item}")
    if not holding("{item}"):
        pick("{item}")
    if not holding("{item}"):
        pick("{item}")
    assert holding("{item}")
    place("{item}", "{target}")
    assert on("{item}", "{target}")
    assert hand_empty()
"""
                report = check_program(program, bundle)
                self.assertEqual(report["status"], "passed", report["errors"])
                self.assertTrue(report["goal_met"])
                self.assertEqual([a["action"] for a in report["actions"]], ["inspect", "pick", "place"])
                self.assertEqual([a["recovery_taken"] for a in report["assertions"] if a["kind"] == "guard"],
                                 [True, False])
                self.assertEqual(bundle, original)

    def test_failure_reports_line_and_preserves_initial_scene(self):
        bundle = task("cup_to_tray")
        program = 'def plan():\n    pick("cup_1")\n    assert hand_empty()\n    place("cup_1", "tray_1")'
        report = check_program(program, bundle)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["errors"][0]["phase"], "assertion")
        self.assertEqual(report["errors"][0]["line"], 3)
        self.assertEqual(len(report["actions"]), 1)
        self.assertEqual(report["final_state"], bundle["scene"])
        incomplete = check_program('def plan():\n    pick("cup_1")', bundle)
        self.assertEqual(incomplete["errors"][0]["rule_id"], "goal_unmet")
        bundle["scene"]["tray"]["occupied"] = True
        report = check_program('def plan():\n    pick("cup_1")\n    place("cup_1", "tray_1")', bundle)
        self.assertEqual(report["errors"][0]["rule_id"], "destination_occupied")
        bundle["scene"]["cup"]["empty"] = False
        report = check_program('def plan():\n    inspect("cup_1")', bundle)
        self.assertEqual(report["errors"][0]["rule_id"], "cup_condition")
        self.assertEqual(report["actions"], [])

    def test_entire_program_is_checked_before_the_first_action(self):
        bundle = task("cup_to_tray")
        prefix = 'def plan():\n    inspect("cup_1")\n    if not hand_empty():\n        '
        for body in ('pick("apple_1")', 'pick("tray_1")', 'pick()', 'pick(1)', 'inspect(object="cup_1")',
                     'open("cup_1")', 'inspect(str("cup_1"))', 'assert holding(cup_1)',
                     'assert unknown()', '"a string outside the leading docstring"', 'import math'):
            with self.subTest(body=body):
                report = check_program(prefix + body, bundle)
                self.assertEqual(report["status"], "invalid_program")
                self.assertEqual(report["actions"], [])
        for program in ('def other():\n    hand_empty()', 'def plan(x=None):\n    hand_empty()',
                        '@wrapper\ndef plan():\n    pass', 'def plan():\n    pass\nplan()',
                        'def plan():\n' + '    inspect("cup_1")\n' * 65):
            with self.subTest(program=program[:50]):
                self.assertEqual(check_program(program, bundle)["status"], "invalid_program")
