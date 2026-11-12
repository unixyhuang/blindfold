"""Exercise official Evolving Graph semantics on the three authored kitchen graphs."""
import hashlib
import json
import re
from pathlib import Path
import unittest

from simulators.evolving_graph import EvolvingGraphClient, UPSTREAM_COMMIT
from simulators.virtualhome import bind_scene, compile_script, execute_transfer
from third_party.virtualhome_evolving_graph.environment import Property


TASKS = Path(__file__).resolve().parents[1] / "tasks"


def load_task(name):
    return json.loads((TASKS / f"{name}.json").read_text(encoding="utf-8"))


def edge(graph, source, relation, target):
    return any(e["from_id"] == source and e["relation_type"] == relation and e["to_id"] == target
               for e in graph["edges"])


class EvolvingGraphTests(unittest.TestCase):
    def test_vendored_engine_and_license_match_pinned_snapshot(self):
        source = TASKS.parent / "third_party" / "virtualhome_evolving_graph"
        notice = (source / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn(UPSTREAM_COMMIT, notice)
        hashes = dict(re.findall(r"^\| ([\w.]+) \| `([0-9a-f]{64})` \|$", notice, re.MULTILINE))
        self.assertEqual(set(hashes), {"common.py", "environment.py", "scripts.py", "execution.py", "LICENSE"})
        for filename, expected in hashes.items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((source / filename).read_bytes()).hexdigest(), expected)

    def test_bridge_verifies_all_three_real_engine_results(self):
        for task in ("apple_to_counter", "cup_to_tray", "cup_to_counter"):
            with self.subTest(task=task):
                bundle = load_task(task)
                client = EvolvingGraphClient(bundle)
                plan = {"status": "passed", "source": "recorded_reference", "actions": bundle["actions"]}
                result = execute_transfer(bundle, plan, client)
                self.assertEqual(result["status"], "passed", result)
                self.assertIs(result["goal_met"], True)
                self.assertEqual(result["reset_protocol"], "evolving_graph")
                self.assertTrue(all(step["success"] is True for step in result["execution"]))
                item_name, dest_name = bundle["goal"]["on"]
                item = result["bindings"][item_name]
                destination = result["bindings"][dest_name]
                table = result["bindings"]["table_1"]
                self.assertTrue(edge(result["before_graph"], item, "ON", table))
                self.assertTrue(edge(result["after_graph"], item, "ON", destination))
                self.assertFalse(edge(result["after_graph"], item, "ON", table))
                self.assertFalse(any(e["from_id"] == result["character_id"] and
                                     e["relation_type"] in {"HOLDS_LH", "HOLDS_RH"}
                                     for e in result["after_graph"]["edges"]))

    def test_holding_is_observed_between_grab_and_placement(self):
        bundle = load_task("cup_to_counter")
        client = EvolvingGraphClient(bundle)
        client.reset(0)
        client.add_character()
        before = client.environment_graph()
        bindings = bind_scene(bundle, before)
        steps = compile_script(bundle["actions"], before, bindings)
        grabbed, message = client.render_script([s["line"] for s in steps if s["action_index"] == 0])
        self.assertTrue(grabbed, message)
        held = client.environment_graph()
        actor = next(n["id"] for n in held["nodes"] if n["class_name"] == "character")
        self.assertTrue(any(edge(held, actor, r, bindings["cup_1"]) for r in ("HOLDS_LH", "HOLDS_RH")))
        self.assertFalse(edge(held, bindings["cup_1"], "ON", bindings["table_1"]))
        held["edges"].clear()
        self.assertTrue(client.environment_graph()["edges"])
        placed, message = client.render_script([s["line"] for s in steps if s["action_index"] == 1])
        self.assertTrue(placed, message)
        self.assertTrue(edge(client.environment_graph(), bindings["cup_1"], "ON", bindings["counter_1"]))
        client.reset(0)
        unoccupied = client.environment_graph()
        self.assertTrue(edge(unoccupied, bindings["cup_1"], "ON", bindings["table_1"]))
        self.assertFalse(any(n["class_name"] == "character" for n in unoccupied["nodes"]))

    def test_upstream_grab_rejects_item_missing_grabbable(self):
        bundle = load_task("cup_to_counter")
        client = EvolvingGraphClient(bundle)
        client.reset(0)
        client.add_character()
        graph = client.environment_graph()
        bindings = bind_scene(bundle, graph)
        item = bindings["cup_1"]
        # Negative control: remove exactly one property on the real engine node.
        client._state.get_node(item).properties.remove(Property.GRABBABLE)
        steps = compile_script(bundle["actions"], graph, bindings)
        accepted, message = client.render_script([s["line"] for s in steps])
        self.assertFalse(accepted)
        self.assertIn("is not grabbable", message)
        final = client.environment_graph()
        self.assertTrue(edge(final, item, "ON", bindings["table_1"]))
        self.assertFalse(edge(final, item, "ON", bindings["counter_1"]))

    def test_rejects_unavailable_scene_room_character_or_command(self):
        client = EvolvingGraphClient(load_task("apple_to_counter"))
        with self.assertRaises(ValueError):
            client.reset(1)
        client.reset(0)
        with self.assertRaises(ValueError):
            client.add_character(initial_room="bedroom")
        client.add_character()
        with self.assertRaises(ValueError):
            client.add_character()
        before = client.environment_graph()
        for line in ("<char1> [walk] <apple> (4)", "<char0> [walk] <tray> (4)",
                     "<char0> [grab] <apple> (999)", "<char0> [type] <apple> (4)"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                client.render_script([line])
        self.assertEqual(before, client.environment_graph())


if __name__ == "__main__":
    unittest.main()
