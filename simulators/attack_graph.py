"""Execute a verified attack chain in the bundled VirtualHome Evolving Graph engine.

The chain is compiled to native VirtualHome script lines (FIND, WALK, GRAB,
OPEN, PUTIN, PUT, CLOSE), executed one line at a time, and then checked from
the returned graph. This is the symbolic VirtualHome engine; it does not run
Unity assets or native physics.
"""

from copy import deepcopy

from third_party.virtualhome_evolving_graph.environment import EnvironmentGraph, EnvironmentState
from third_party.virtualhome_evolving_graph.execution import ScriptExecutor
from third_party.virtualhome_evolving_graph.scripts import read_script_from_list_string
from verifier.attack import validate_task, verify_chain


BACKEND = "virtualhome_evolving_graph_attack"
UPSTREAM_COMMIT = "58970fd80951c2eaa1af713e0917d1a105353ad8"
HOLDS = {"HOLDS_LH", "HOLDS_RH"}
ROOM_NAMES = {"kitchen", "bedroom", "livingroom", "bathroom", "home"}


def _node(node_id, class_name, category, properties=(), states=()):
    return {"id": node_id, "class_name": class_name, "category": category,
            "properties": list(properties), "states": list(states)}


def _edge(source, relation, target):
    return {"from_id": source, "to_id": target, "relation_type": relation}


def _node_map(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError("Expected a complete VirtualHome graph with nodes and edges.")
    return {node["id"]: node for node in graph["nodes"]}


class AttackGraphClient:
    """Build one authored VirtualHome scene for an attack task and execute its chain."""

    backend = BACKEND
    upstream_commit = UPSTREAM_COMMIT
    reset_protocol = "evolving_graph"

    def __init__(self, bundle):
        validate_task(bundle)
        self.bundle = deepcopy(bundle)
        self.bindings = {}
        self.room_id = None
        self._setup = None
        self._state = None
        self._executor = None

    def check_connection(self):
        return True

    def reset(self, environment=0):
        if environment != 0:
            raise ValueError("The bundled attack graph provides only environment 0.")
        self.bindings = {}
        scene = self.bundle["scene"]
        locations = list(scene["locations"])
        room = next((name for name in locations if name in ROOM_NAMES), None)
        nodes = []
        edges = []
        next_id = 1
        if room is None:
            nodes.append(_node(next_id, "kitchen", "Rooms"))
            self.room_id = next_id
            next_id += 1
        else:
            nodes.append(_node(next_id, room, "Rooms"))
            self.room_id = next_id
            self.bindings[room] = next_id
            next_id += 1
        for location in locations:
            if location == room:
                continue
            nodes.append(_node(next_id, location, "Furniture", ("SURFACES",)))
            edges.append(_edge(next_id, "INSIDE", self.room_id))
            self.bindings[location] = next_id
            next_id += 1
        for object_id, record in scene["objects"].items():
            container = "open" in record
            properties = ("CAN_OPEN",) if container else ("GRABBABLE",)
            states = (("OPEN",) if record["open"] else ("CLOSED",)) if container else ()
            nodes.append(_node(next_id, record["type"], "Props", properties, states))
            edges.append(_edge(next_id, "INSIDE", self.room_id))
            location = record["location"]
            if location in self.bindings and location != room:
                edges.append(_edge(next_id, "ON", self.bindings[location]))
            elif location in scene["objects"]:
                edges.append(_edge(next_id, "INSIDE", self.bindings[location]))
            self.bindings[object_id] = next_id
            next_id += 1
        self._setup = {"nodes": nodes, "edges": edges}
        self._state = None
        self._executor = None

    def add_character(self, resource="Chars/Male1", initial_room="kitchen"):
        if self._setup is None or self._executor is not None:
            raise ValueError("Reset the scene before adding its character.")
        graph_dict = deepcopy(self._setup)
        character_id = max(node["id"] for node in graph_dict["nodes"]) + 1
        graph_dict["nodes"].append(_node(character_id, "character", "Characters", ("PERSON",)))
        graph_dict["edges"].append(_edge(character_id, "INSIDE", self.room_id))
        graph = EnvironmentGraph(graph_dict)
        self._executor = ScriptExecutor(graph, {}, char_index=0)
        self._state = EnvironmentState(graph, {}, instance_selection=True)
        self.character_id = character_id

    def environment_graph(self):
        if self._setup is None:
            raise ValueError("Reset the scene before requesting its graph.")
        observed = self._setup if self._state is None else self._state.to_dict()
        return deepcopy(observed)

    def render_script(self, script):
        if self._executor is None:
            raise ValueError("Add the character before executing a chain.")
        if not isinstance(script, list) or not script:
            raise ValueError("Expected a nonempty list of character action lines.")
        for line in script:
            if not isinstance(line, str) or not line.startswith("<char0> "):
                raise ValueError("The authored graph accepts only commands for <char0>.")
            command = line[len("<char0> "):].strip()
            self._executor.info.messages.clear()
            success, self._state = self._executor.execute_one_step(
                read_script_from_list_string([command]), self._state)
            if not success:
                return False, self._executor.info.get_error_string()
        return True, "VirtualHome executed the supplied action lines."


def _argument(node):
    return f"<{node['class_name']}> ({node['id']})"


def _compile(chain, bindings, graph):
    nodes = _node_map(graph)

    def argument(symbol):
        return _argument(nodes[bindings[symbol]])

    script = []
    for index, action in enumerate(chain):
        name = action["action"]
        parameters = action["parameters"]
        if name == "find":
            object_argument = argument(parameters[0])
            commands = [("walk", object_argument), ("find", object_argument)]
        elif name == "move_to":
            commands = [("walk", argument(parameters[0]))]
        elif name == "pick_up":
            object_argument = argument(parameters[0])
            commands = [("walk", object_argument), ("grab", object_argument)]
        elif name in ("open", "close"):
            container = argument(parameters[0])
            commands = [("walk", container), (name, container)]
        elif name == "put_in":
            commands = [("walk", argument(parameters[1])),
                        ("putin", f"{argument(parameters[0])} {argument(parameters[1])}")]
        elif name == "place":
            commands = [("walk", argument(parameters[1])),
                        ("putback", f"{argument(parameters[0])} {argument(parameters[1])}")]
        else:
            raise ValueError(f"Unsupported attack action: {name!r}.")
        script.extend({"action_index": index, "action": name,
                       "line": f"<char0> [{command}] {arguments}"}
                      for command, arguments in commands)
    return script


def observe_attack_goal(bundle, graph, bindings):
    """Read the terminal relations and container states from the VirtualHome graph."""
    nodes = _node_map(graph)
    checks = []
    for object_id, container_id in bundle["goal"]["in"]:
        inside = any(edge["from_id"] == bindings[object_id] and edge["to_id"] == bindings[container_id]
                     and edge["relation_type"].upper() == "INSIDE" for edge in graph["edges"])
        checks.append({"rule": "item_inside_container", "value": inside,
                       "from_id": bindings[object_id], "to_id": bindings[container_id]})
    for container_id in bundle["goal"]["closed"]:
        states = {state.upper() for state in nodes[bindings[container_id]]["states"]}
        closed = "OPEN" not in states and "CLOSED" in states
        checks.append({"rule": "container_closed", "value": closed, "node_id": bindings[container_id]})
    character_id = next((node_id for node_id, node in nodes.items()
                         if node["class_name"].lower() == "character"
                         or str(node.get("category", "")).lower() == "characters"), None)
    empty = character_id is not None and not any(
        edge["from_id"] == character_id and edge["relation_type"].upper() in HOLDS
        for edge in graph["edges"])
    checks.append({"rule": "character_hands_empty", "value": empty, "character_id": character_id})
    passed = all(check["value"] for check in checks)
    return {"status": "supported" if passed else "contradicted", "checks": checks}


def execute_attack(bundle, chain, *, environment=0):
    """Execute an already verified chain in the bundled VirtualHome engine."""
    report = {"task_id": bundle.get("task_id"), "backend": BACKEND,
              "upstream_commit": UPSTREAM_COMMIT, "status": "not_run", "stage": "verification",
              "environment": environment, "script": [], "execution": [],
              "goal_met": None, "observed_goal": None}
    checked = verify_chain(bundle, chain)
    report["symbolic_recheck"] = checked
    if checked["status"] != "passed":
        report["status"] = "invalid_plan"
        return report
    client = AttackGraphClient(bundle)
    rejected = False
    try:
        report["stage"] = "scene_setup"
        client.reset(environment)
        client.add_character()
        before = client.environment_graph()
        report.update(before_graph=before, bindings=deepcopy(client.bindings),
                      character_id=client.character_id)
        script = _compile(chain, client.bindings, before)
        report.update(script=script, stage="execution")
        for index, step in enumerate(script):
            entry = {"script_index": index, **step, "success": None, "message": None}
            report["execution"].append(entry)
            success, message = client.render_script([step["line"]])
            entry.update(success=success, message=message)
            if not success:
                rejected = True
                break
        report["stage"] = "observation"
        after = client.environment_graph()
        observed = observe_attack_goal(bundle, after, client.bindings)
        report.update(after_graph=after, observed_goal=observed,
                      goal_met=observed["status"] == "supported")
        report["status"] = "execution_failed" if rejected else (
            "passed" if observed["status"] == "supported" else "failed")
        report["stage"] = "complete"
    except (ValueError, KeyError, RuntimeError) as error:
        report["error"] = str(error)
        report["status"] = "execution_failed" if rejected else "error"
    return report

