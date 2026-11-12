import unittest

from progprompt.benchmark_runtime import check_benchmark_program


OBJECTS = {"mug", "desk", "cabinet", "bowl"}
REFERENCE = ["find mug", "pick mug", "find desk", "put desk"]


def assess(body, goal=None, steps=REFERENCE):
    record = {"task_id": "test-mug", "scene_name": "FloorPlan1",
              "instruction": "Put the mug on the desk.", "step": steps,
              "final_state": [{"objectType": "Mug", "parentReceptacles": ["Desk"]}] if goal is None else goal}
    return check_benchmark_program("def plan():\n" + body, record, OBJECTS)


class BenchmarkProgramTests(unittest.TestCase):
    def test_generated_recovery_branch_is_executed_only_when_needed(self):
        program = '''    if not seen("Mug"):
        find("mug")
    if not seen("mug"):
        pick("mug")
    assert hand_empty()
    pick("mug")
    assert holding("mug")
    find("desk")
    put("desk")
    assert hand_empty()'''
        result = assess(program, steps=["not a reference action"])
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["generated_steps"], REFERENCE)
        self.assertEqual([e["recovery_taken"] for e in result["assertions"] if e["kind"] == "guard"], [True, False])

    def test_bad_generated_plan_does_not_inherit_known_good_reference(self):
        result = assess('    pick("mug")')
        self.assertEqual(result["status"], "contradicted")
        self.assertEqual(result["goal_status"], "unknown")
        self.assertEqual(result["generated_steps"], ["pick mug"])
        self.assertEqual(result["issues"][0]["rule"], "no_prior_find")
        self.assertEqual(result["issues"][0]["line"], 2)
        self.assertEqual(result["issues"][0]["step_index"], 0)
        incomplete = assess('    find("mug")')
        self.assertEqual(incomplete["status"], "unknown")
        self.assertEqual(incomplete["issues"][0]["rule"], "missing_generated_goal_evidence")

    def test_unknown_guard_and_failed_assertion_stop_before_later_actions(self):
        unknown = assess('    if not is_open("cabinet"):\n        find("cabinet")\n    find("mug")')
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNone(unknown["assertions"][0]["value"])
        self.assertEqual(unknown["issues"][0]["rule"], "unknown_predicate")
        self.assertEqual(unknown["generated_steps"], [])
        failed = assess('    find("mug")\n    assert holding("mug")\n    pick("mug")')
        self.assertEqual(failed["status"], "contradicted")
        self.assertEqual(failed["issues"][0]["rule"], "assertion_false")
        self.assertEqual(failed["generated_steps"], ["find mug"])

    def test_unknown_guard_becomes_known_when_opened_or_closed(self):
        goal = [{"objectType": "Cabinet", "isOpen": False}]
        result = assess('    find("cabinet")\n    open("cabinet")\n    assert is_open("cabinet")\n'
                        '    close("cabinet")\n    if not is_open("cabinet"):\n        find("mug")', goal)
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["assertions"][-1]["recovery_taken"], True)
        self.assertEqual(result["generated_steps"][-1], "find mug")

    def test_negated_assertion_preserves_unknown_and_checks_updated_state(self):
        closed = [{"objectType": "Cabinet", "isOpen": False}]
        prefix = '    find("cabinet")\n'
        assertion = '    assert not is_open("cabinet")'
        for effect, expected, value in [("", "unknown", None), ('    open("cabinet")\n', "contradicted", False),
                                        ('    close("cabinet")\n', "supported", True)]:
            with self.subTest(effect=effect):
                result = assess(prefix + effect + assertion, closed)
                self.assertEqual(result["status"], expected)
                self.assertIs(result["assertions"][0]["value"], value)
                self.assertEqual(result["assertions"][0]["expression"], "not is_open('cabinet')")
        invalid = assess('    assert not invent("mug")')
        self.assertEqual(invalid["issues"][0]["rule"], "unsupported_primitive")

    def test_boolean_assertion_does_not_supply_an_action_or_goal_fact(self):
        self.assertEqual(assess("    assert True")["issues"][0]["rule"], "no_generated_steps")
        self.assertEqual(assess("    assert False")["issues"][0]["rule"], "assertion_false")
        self.assertEqual(assess("    assert 1")["status"], "invalid_program")
        result = assess('    find("cabinet")\n    open("cabinet")\n    assert True',
                        [{"objectType": "Cabinet", "isOpen": False}])
        self.assertEqual(result["assertions"][0]["value"], True)
        self.assertEqual(result["goal_status"], "contradicted")

    def test_invalid_or_ungrounded_calls_rejected_even_in_skipped_branch(self):
        for line, rule in [('import math', 'unsupported_statement'), ('find("plate")', 'object_outside_inventory'),
                           ('invent("mug")', 'unsupported_primitive'), ('find(str("mug"))', 'nonliteral_argument'),
                           ('put("mug", "desk")', 'wrong_arguments'), ('fill_liquid("mug","milk")', 'unsupported_liquid')]:
            with self.subTest(line=line):
                result = assess('    find("mug")\n    if not hand_empty():\n        ' + line)
                self.assertEqual(result["status"], "invalid_program")
                self.assertEqual(result["generated_steps"], [])
                self.assertEqual(result["issues"][0]["rule"], rule)

    def test_missing_vs_unobserved_transfer(self):
        goal = [{"objectType": "Bowl", "liquidReceived": {"liquid": "water", "source": "Mug", "relation": "into"}}]
        body = '    find("mug")\n    fill_liquid("mug","water")\n    pick("mug")\n    find("bowl")'
        self.assertEqual(assess(body, goal)["issues"][0]["rule"], "missing_generated_pour")
        poured = assess(body + '\n    pour()', goal)
        self.assertEqual(poured["status"], "unknown")
        self.assertEqual(poured["issues"][0]["rule"], "unobserved_liquid_transfer")
        self.assertIn("fillLiquid mug water", poured["generated_steps"])

    def test_empty_effect_and_goal_contradiction(self):
        empty = assess("    assert hand_empty()")
        self.assertEqual(empty["issues"][0]["rule"], "no_generated_steps")
        result = assess('    find("cabinet")\n    open("cabinet")',
                        [{"objectType": "Cabinet", "isOpen": False}])
        self.assertEqual(result["trace_status"], "consistent")
        self.assertEqual(result["goal_status"], "contradicted")
        self.assertEqual(result["issues"][0]["rule"], "goal_mismatch")
