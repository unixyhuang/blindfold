"""Regression checks for instance-based final-state observations."""

import unittest

from verifier.observations import evaluate_snapshot


def evaluate(goals, objects):
    record = {"scene_name": "FloorPlan2", "final_state": goals}
    metadata = {"sceneName": "FloorPlan2_physics", "objects": objects}
    return evaluate_snapshot(record, metadata)


class ObservationTests(unittest.TestCase):
    def test_one_instance_must_meet_all_fields(self):
        goal = {"objectType": "Mug", "isPickedUp": False, "isFilledWithLiquid": True}
        objects = [
            {"objectId": "a", "objectType": "Mug", "isPickedUp": False, "isFilledWithLiquid": False},
            {"objectId": "b", "objectType": "Mug", "isPickedUp": True, "isFilledWithLiquid": True},
        ]
        self.assertEqual(evaluate([goal], objects)["status"], "contradicted")
        del objects[1]["isPickedUp"]
        self.assertEqual(evaluate([goal], objects)["status"], "unknown")
        objects[1]["isPickedUp"] = False
        self.assertEqual(evaluate([goal], objects)["status"], "supported")

    def test_relations_use_ids_and_allow_matching_among_multiple_parents(self):
        goals = [
            {"objectType": "Bowl", "isFilledWithLiquid": True, "parentReceptacles": ["Fridge", "Table"]},
            {"objectType": "Fridge", "isOpen": False, "receptacleObjectIds": ["Bowl"]},
        ]
        objects = [
            {"objectId": "obj/7", "objectType": "Bowl", "isFilledWithLiquid": True,
             "parentReceptacles": ["obj/2"]},
            {"objectId": "obj/2", "objectType": "Fridge", "isOpen": False,
             "receptacleObjectIds": ["obj/7"]},
        ]
        self.assertEqual(evaluate(goals, objects)["status"], "supported")
        objects[0]["parentReceptacles"] = ["Fridge|unknown-id"]
        self.assertEqual(evaluate(goals, objects)["status"], "unknown")
        objects[0]["parentReceptacles"] = []
        self.assertEqual(evaluate(goals, objects)["status"], "contradicted")

    def test_contents_accept_any_requested_type(self):
        goal = {"objectType": "Box", "receptacleObjectIds": ["Mug", "Bowl"]}
        objects = [
            {"objectType": "Box", "objectId": "box", "receptacleObjectIds": ["cup"]},
            {"objectType": "Mug", "objectId": "cup"},
        ]
        self.assertEqual(evaluate([goal], objects)["status"], "supported")

    def test_missing_relations_distinct_from_empty_lists(self):
        for field in ("parentReceptacles", "receptacleObjectIds"):
            with self.subTest(field=field):
                goal = {"objectType": "Box", field: ["Mug"]}
                obj = {"objectType": "Box", "objectId": "box"}
                self.assertEqual(evaluate([goal], [obj])["status"], "unknown")
                obj[field] = []
                self.assertEqual(evaluate([goal], [obj])["status"], "contradicted")

    def test_absent_annotation_and_absent_object(self):
        self.assertEqual(evaluate(None, []), {"checks": [], "status": "unknown"})
        self.assertEqual(evaluate([], []), {"checks": [], "status": "unknown"})
        self.assertEqual(evaluate([{"objectType": "Mug", "isPickedUp": True}], [])["status"], "contradicted")

    def test_reject_wrong_scene_and_invalid_objects(self):
        record = {"scene_name": "FloorPlan2", "final_state": []}
        obj = {"objectId": "duplicate", "objectType": "Cabinet"}
        for metadata in [
            {"sceneName": "FloorPlan21", "objects": []}, {"sceneName": "FloorPlan2"},
            {"sceneName": "FloorPlan2", "objects": [obj, obj]}, {"sceneName": "FloorPlan2", "objects": [{}]},
        ]:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                evaluate_snapshot(record, metadata)
        with self.assertRaises(ValueError):
            evaluate([{"objectType": "Cabinet", "isOpen": False}], [dict(obj, isOpen=0)])
