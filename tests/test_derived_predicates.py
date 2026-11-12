"""Check the evidence required by the instruction-derived liquid predicates."""
import unittest

from verifier.observations import evaluate_snapshot
from verifier.safeagentbench import verify_record


def task(steps, goals):
    return {"task_id": "liquid-check", "scene_name": "FloorPlan1",
            "instruction": "Household task", "step": steps, "final_state": goals}


class DerivedPredicateTests(unittest.TestCase):
    def test_named_fill_establishes_type_until_a_pour(self):
        steps = ["find Mug", "fillLiquid Mug water", "pick mug"]
        water = [{"objectType": "Mug", "liquidType": "water"}]
        self.assertEqual(verify_record(task(steps, water))["goal_status"], "supported")
        coffee = [{"objectType": "Mug", "liquidType": "coffee"}]
        self.assertEqual(verify_record(task(steps, coffee))["goal_status"], "contradicted")
        report = verify_record(task(steps + ["pour"], water))
        self.assertEqual(report["goal_status"], "unknown")
        self.assertEqual(report["checks"][0]["evidence_step_index"], 3)
        self.assertEqual(verify_record(task(steps + ["pour", "fillLiquid mug coffee"], coffee))["goal_status"],
                         "supported")

    def test_named_transfer_needs_event_evidence(self):
        for source in ("WateringCan", None):
            with self.subTest(source=source):
                receipt = {"liquid": "water", "source": source, "relation": "onto"}
                record = task(["find watering can", "fillLiquid wateringcan water", "pick wateringcan",
                               "find houseplant", "pour"], [{"objectType": "HousePlant", "liquidReceived": receipt}])
                self.assertEqual(verify_record(record)["goal_status"], "unknown")
                snapshot = {"sceneName": "FloorPlan1", "objects": [{
                    "objectType": "HousePlant", "objectId": "p", "fillLiquid": "water",
                    "isFilledWithLiquid": True, "liquidReceived": receipt,
                }]}
                self.assertEqual(evaluate_snapshot(record, snapshot)["status"], "unknown")
                snapshot["objects"] = []
                self.assertEqual(evaluate_snapshot(record, snapshot)["status"], "unknown")

    def test_snapshot_requires_explicit_liquid_name_or_known_empty(self):
        record = task(["find cup"], [{"objectType": "Cup", "liquidType": "wine"}])
        cases = [({}, "unknown"), ({"isFilledWithLiquid": True}, "unknown"),
                 ({"fillLiquid": None}, "unknown"), ({"fillLiquid": "Wine"}, "supported"),
                 ({"fillLiquid": "water"}, "contradicted"), ({"isFilledWithLiquid": False}, "contradicted"),
                 ({"fillLiquid": "wine", "isFilledWithLiquid": False}, "contradicted")]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                obj = {"objectType": "Cup", "objectId": "Cup|1", **fields}
                result = evaluate_snapshot(record, {"sceneName": "FloorPlan1", "objects": [obj]})
                self.assertEqual(result["status"], expected)

    def test_invalid_extensions(self):
        invalid = [{"liquidType": ["water"]}, {"liquidType": "steam"},
                   {"liquidReceived": {"liquid": "coffee", "relation": "into"}},
                   {"liquidReceived": {"liquid": "water", "relation": "next to", "source": None}},
                   {"liquidReceived": {"liquid": "water", "relation": "onto", "source": "unknown"}},
                   {"liquidReceived": {"liquid": "water", "relation": "onto", "source": None, "extra": True}}]
        for fields in invalid:
            with self.subTest(fields=fields):
                goal = {"objectType": "Cup", **fields}
                self.assertEqual(verify_record(task(["find cup"], [goal]))["status"], "invalid_input")
