import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from progprompt.optimization import MAX_ACTIONS, TASK_FILES, optimize_actions, repair_actions
from verifier.tabletop import verify_task


TASK_DIRECTORY = Path(__file__).resolve().parents[1] / "tasks"


def task_and_actions(filename):
    bundle = json.loads((TASK_DIRECTORY / filename).read_text(encoding="utf-8"))
    item, target = bundle["goal"]["on"]
    return bundle, {"action": "inspect", "object": item}, {"action": "pick", "object": item}, {
        "action": "place", "object": item, "target": target}


class TransferOptimizationTests(unittest.TestCase):
    def test_three_tasks_optimize_shorter_without_changing_goal_or_final_state(self):
        for filename in TASK_FILES.values():
            with self.subTest(filename=filename):
                bundle, inspect, pick, place = task_and_actions(filename)
                # Reference actions must never be used as a generated answer.
                bundle["actions"] = [{"action": "unsupported_reference"}]
                actions = [inspect, deepcopy(inspect), pick, deepcopy(inspect), place, deepcopy(inspect)]
                saved_bundle, saved_actions = deepcopy(bundle), deepcopy(actions)
                result = optimize_actions(bundle, actions)
                self.assertEqual(result["status"], "optimized")
                self.assertEqual(result["candidate_actions"], [pick, place])
                self.assertEqual(result["candidate_original_indices"], [2, 4])
                self.assertEqual(result["original_actions"], actions)
                self.assertEqual(len(result["changes"]), 4)
                self.assertTrue(all(change["operation"] == "remove" for change in result["changes"]))
                self.assertEqual(result["goal"], bundle["goal"])
                self.assertEqual(result["before_verifier"]["final_state"], result["verifier"]["final_state"])
                self.assertTrue(result["equivalent"])
                self.assertTrue(result["verifier"]["goal_met"])
                self.assertEqual((bundle, actions), (saved_bundle, saved_actions))

    def test_minimal_passed_trace_is_unchanged(self):
        bundle, _, pick, place = task_and_actions("cup_to_counter.json")
        result = optimize_actions(bundle, [pick, place])
        self.assertEqual((result["status"], result["reason"]), ("unchanged", "already_minimal"))
        self.assertEqual(result["changes"], [])
        self.assertTrue(result["equivalent"])

    def test_optimization_never_repairs_a_failed_input(self):
        bundle, _, pick, place = task_and_actions("cup_to_tray.json")
        actions = [place, pick]
        result = optimize_actions(bundle, actions)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["reason"], "requires_verifier_repair")
        self.assertEqual(result["candidate_actions"], actions)
        self.assertFalse(result["equivalent"])
        self.assertEqual(result["changes"], [])

    def test_repair_fills_only_missing_primitives_on_all_three_tasks(self):
        for filename in TASK_FILES.values():
            bundle, inspect, pick, place = task_and_actions(filename)
            for actions, inserts in (([], 2), ([inspect], 2), ([place], 1), ([pick], 1), ([place, pick], 0)):
                with self.subTest(filename=filename, actions=actions):
                    feedback = verify_task({**bundle, "actions": actions})
                    saved = deepcopy((bundle, actions, feedback))
                    result = repair_actions(bundle, actions, feedback)
                    self.assertEqual(result["status"], "repaired")
                    self.assertEqual(result["before_verifier"], feedback)
                    self.assertFalse(result["equivalent"])
                    self.assertEqual(result["verifier"]["status"], "passed")
                    self.assertEqual(result["goal"], bundle["goal"])
                    self.assertEqual(sum(change["operation"] == "insert" for change in result["changes"]), inserts)
                    self.assertFalse(any(change["operation"] == "remove" for change in result["changes"]))
                    retained = [source for source in result["candidate_original_indices"] if source is not None]
                    self.assertEqual(sorted(retained), list(range(len(actions))))
                    for action, source in zip(result["candidate_actions"], result["candidate_original_indices"]):
                        if source is not None:
                            self.assertEqual(action, actions[source])
                    self.assertEqual((bundle, actions, feedback), saved)

    def test_repair_reorders_with_no_unnecessary_insertions(self):
        bundle, inspect, pick, place = task_and_actions("apple_to_counter.json")
        actions = [place, inspect, pick]
        result = repair_actions(bundle, actions, verify_task({**bundle, "actions": actions}))
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(len(result["candidate_actions"]), len(actions))
        self.assertTrue(any(change["operation"] == "reorder" for change in result["changes"]))
        self.assertFalse(any(change["operation"] == "insert" for change in result["changes"]))

    def test_repair_does_not_change_a_passed_trace(self):
        bundle, inspect, pick, place = task_and_actions("cup_to_tray.json")
        actions = [inspect, pick, place]
        result = repair_actions(bundle, actions, verify_task({**bundle, "actions": actions}))
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["reason"], "already_passed")
        self.assertEqual(result["candidate_actions"], actions)
        self.assertTrue(result["equivalent"])

    def test_repair_cannot_drop_duplicate_state_changing_actions(self):
        bundle, _, pick, place = task_and_actions("cup_to_counter.json")
        for actions in ([pick, pick, place], [pick, place, place], [place, pick, pick]):
            with self.subTest(actions=actions):
                result = repair_actions(bundle, actions, verify_task({**bundle, "actions": actions}))
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["candidate_actions"], actions)
                self.assertEqual(result["changes"], [])
                self.assertFalse(result["verifier"]["goal_met"])

    def test_feedback_is_recomputed_instead_of_trusting_a_verdict(self):
        bundle, _, pick, place = task_and_actions("cup_to_tray.json")
        actions = [place]
        actual = verify_task({**bundle, "actions": actions})
        passed_for_other_trace = verify_task({**bundle, "actions": [pick, place]})
        wrong_status = {**actual, "status": "passed"}
        wrong_index_type = {**actual, "index_base": False}
        extra_field = {**actual, "claim": "from verifier"}
        for feedback in (passed_for_other_trace, wrong_status, wrong_index_type, extra_field, {}, None):
            with self.subTest(feedback=feedback):
                with self.assertRaisesRegex(ValueError, "Feedback does not exactly match"):
                    repair_actions(bundle, actions, feedback)

    def test_wrong_objects_targets_unsupported_and_extra_actions_are_rejected(self):
        bundle, inspect, pick, place = task_and_actions("cup_to_tray.json")
        invalid = [
            [{**pick, "object": "apple_1"}], [{**place, "target": "counter_1"}],
            [{**pick, "action": "heat"}], [{**pick, "action": "pour"}],
            [{**inspect, "extra": 1}], [{**place, "comment": "extra"}],
            [{"action": "pick"}], [{**pick, "target": "tray_1"}], [None], ["pick(cup_1)"],
        ]
        for actions in invalid:
            with self.subTest(actions=actions):
                with self.assertRaises(ValueError):
                    optimize_actions(bundle, actions)
                with self.assertRaises(ValueError):
                    repair_actions(bundle, actions, {})

    def test_task_identity_scene_and_goal_cannot_be_changed(self):
        bundle, _, pick, place = task_and_actions("cup_to_tray.json")
        changed_scene = deepcopy(bundle)
        changed_scene["scene"]["cup"]["empty"] = 1
        changed_goal = deepcopy(bundle)
        changed_goal["goal"]["on"][1] = "counter_1"
        changed_reach = deepcopy(bundle)
        changed_reach["scene"]["arm"]["reachable"].reverse()
        for changed in (changed_scene, changed_goal, changed_reach, {**bundle, "task_id": "other"}, None):
            with self.subTest(bundle=changed):
                with self.assertRaises(ValueError):
                    optimize_actions(changed, [pick, place])
                with self.assertRaises(ValueError):
                    repair_actions(changed, [pick, place], {})

    def test_action_count_and_search_are_bounded(self):
        bundle, inspect, _, _ = task_and_actions("cup_to_tray.json")
        with self.assertRaises(ValueError):
            optimize_actions(bundle, [inspect] * (MAX_ACTIONS + 1))
        actions = [inspect] * MAX_ACTIONS
        result = repair_actions(bundle, actions, verify_task({**bundle, "actions": actions}))
        self.assertEqual(result["status"], "rejected")
        self.assertLessEqual(len(result["candidate_actions"]), MAX_ACTIONS)

    def test_no_model_or_prompt_loading_is_needed(self):
        bundle, _, pick, place = task_and_actions("cup_to_tray.json")
        original_read = Path.read_text

        def tasks_only(path, *args, **kwargs):
            self.assertEqual(path.parent, TASK_DIRECTORY)
            return original_read(path, *args, **kwargs)

        with patch("hf_client.generate_text", side_effect=AssertionError("Model must not load")), \
                patch.object(Path, "read_text", tasks_only):
            self.assertTrue(optimize_actions(bundle, [pick, place])["equivalent"])
            self.assertEqual(repair_actions(bundle, [], verify_task({**bundle, "actions": []}))["status"], "repaired")


if __name__ == "__main__":
    unittest.main()
