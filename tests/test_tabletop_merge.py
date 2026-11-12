import json
import unittest
from copy import deepcopy

from progprompt.tabletop_merge import TASK_DIR, TASK_FILES, check_merge, prepare_merge, render_merge_prompt


def transfer(filename):
    task = json.loads((TASK_DIR / filename).read_text(encoding="utf-8"))
    item, target = task["goal"]["on"]
    inspect = {"id": "look", "action": "inspect", "object": item}
    pick = {"id": "grasp", "action": "pick", "object": item}
    place = {"id": "release", "action": "place", "object": item, "target": target}
    return task, inspect, pick, place


def proposed(*ids):
    return {"status": "merged", "order": list(ids)}


class TabletopMergeTests(unittest.TestCase):
    def test_render_preserves_both_views_of_a_shared_pick(self):
        task, inspect, pick, place = transfer("cup_to_tray.json")
        fragments = [[pick, place], [inspect, pick]]
        rendered = render_merge_prompt({**task, "actions": []}, fragments)
        record, _ = json.JSONDecoder().raw_decode(rendered.split("Input record\n", 1)[1])
        self.assertEqual(record["fragments"], [["grasp", "release"], ["look", "grasp"]])
        self.assertEqual(len(record["events"]), 3)
        self.assertEqual(record["events"]["grasp"]["after"], ["look"])
        self.assertEqual(record["events"]["release"]["after"], ["grasp"])
        self.assertEqual(record["events"]["look"]["after"], [])

    def test_shared_event_replayed_once_on_both_bundled_tasks(self):
        for filename in TASK_FILES.values():
            with self.subTest(filename=filename):
                task, inspect, pick, place = transfer(filename)
                # The adapter must construct actions from fragments, independent of the recorded solution.
                task["actions"] = []
                parts = [[inspect, pick], [dict(pick), place]]
                initial = deepcopy(parts)
                prompt = prepare_merge(task, parts)
                self.assertEqual(set(prompt), {"task_id", "scene", "goal", "fragments"})
                result = check_merge(task, parts, proposed("look", "grasp", "release"))
                self.assertEqual(result["status"], "passed")
                self.assertTrue(result["verifier"]["goal_met"])
                self.assertEqual([e["action"] for e in result["actions"]], ["inspect", "pick", "place"])
                self.assertEqual(parts, initial)

    def test_distinct_ids_preserve_repeated_actions(self):
        task, inspect, pick, place = transfer("apple_to_counter.json")
        parts = [[inspect, pick], [{**inspect, "id": "check"}, place]]
        result = check_merge(task, parts, proposed("look", "check", "grasp", "release"))
        self.assertEqual(result["status"], "passed")
        self.assertEqual([a["action"] for a in result["actions"]].count("inspect"), 2)
        parts = [[pick], [{**pick, "id": "again"}, place]]
        result = check_merge(task, parts, proposed("grasp", "again", "release"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["verifier"]["errors"][0]["rule_id"], "hand_occupied")

    def test_goal_success_cannot_erase_or_invent_input_events(self):
        task, inspect, pick, place = transfer("cup_to_tray.json")
        parts = [[inspect, pick], [place]]
        for order in [("grasp", "release"), ("look", "grasp", "add", "release"),
                      ("look", "grasp", "grasp", "release")]:
            with self.subTest(order=order):
                result = check_merge(task, parts, proposed(*order))
                self.assertEqual(result["errors"][0]["rule_id"], "event_coverage")
        # Opposing order constraints cannot be satisfied by this candidate.
        result = check_merge(task, [[inspect, pick], [pick, inspect, place]], proposed("look", "grasp", "release"))
        self.assertEqual(result["errors"][0]["rule_id"], "fragment_order")

    def test_inputs_are_bound_to_one_canonical_scene_and_goal(self):
        task, inspect, pick, place = transfer("cup_to_tray.json")
        other, *_ = transfer("apple_to_counter.json")
        for changed in [{**task, "scene": other["scene"]}, {**task, "goal": other["goal"]},
                        {**task, "task_id": other["task_id"]}, {**task, "task_id": []}]:
            self.assertEqual(check_merge(changed, [[pick], [place]], proposed("grasp", "release"))["status"],
                             "invalid_input")
        for parts in [[[inspect, inspect], [place]], [[inspect], [{**pick, "id": "look"}]],
                      [[pick], [{**place, "target": "counter_1"}]], [[pick], [{**place, "extra": 1}]],
                      [[{**pick, "object": "apple_1"}], [place]], [[{**pick, "action": "walk"}], [place]]]:
            with self.assertRaises(ValueError):
                prepare_merge(task, parts)

    def test_conflict_is_an_abstention_and_returns_no_replayed_actions(self):
        task, _, pick, place = transfer("cup_to_tray.json")
        parts = [[pick], [place]]
        conflict = check_merge(task, parts, {"status": "conflict", "reason": "No order proposed."})
        self.assertEqual(conflict["status"], "conflict")
        self.assertIsNone(conflict["verifier"])
        self.assertEqual(conflict["actions"], [])
        invalid = check_merge(task, parts, {"status": "merged", "order": ["grasp", "release"], "actions": []})
        self.assertEqual(invalid["status"], "invalid_input")
