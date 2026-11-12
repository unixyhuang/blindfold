"""VirtualHome Evolving Graph backend for the three bundled tabletop transfers."""

from copy import deepcopy

from third_party.virtualhome_evolving_graph.environment import EnvironmentGraph, EnvironmentState
from third_party.virtualhome_evolving_graph.execution import ScriptExecutor
from third_party.virtualhome_evolving_graph.scripts import read_script_from_list_string
from verifier.tabletop import RuleViolation, _check_start, _validate_scene


BACKEND = "virtualhome_evolving_graph"
UPSTREAM_COMMIT = "58970fd80951c2eaa1af713e0917d1a105353ad8"
CHARACTER, ROOM, TABLE, ITEM, DESTINATION = 1, 2, 3, 4, 5


def _node(node_id, class_name, category, *properties):
    return {"id": node_id, "class_name": class_name, "category": category,
            "properties": list(properties), "states": []}


def _edge(source, relation, target):
    return {"from_id": source, "to_id": target, "relation_type": relation}


class EvolvingGraphClient:
    """Keep one upstream EnvironmentState per run, including its execution history."""

    backend = BACKEND
    upstream_commit = UPSTREAM_COMMIT
    reset_protocol = "evolving_graph"

    def __init__(self, bundle):
        scene = bundle.get("scene")
        transfer = _validate_scene(scene)
        try:
            _check_start(scene, transfer)
        except RuleViolation as exc:
            raise ValueError(str(exc)) from exc
        if scene[transfer.destination]["occupied"]:
            raise ValueError("The authored transfer graph requires a free destination slot.")
        if set(scene["arm"]["reachable"]) != {transfer.item_id, transfer.destination_id}:
            raise ValueError("The authored transfer graph requires both task entities to be reachable.")

        self.item = transfer.item
        self.destination = "tray" if transfer.destination == "tray" else "kitchencounter"
        self._setup = None
        self._state = None
        self._executor = None
        item = f"<{self.item}> ({ITEM})"
        target = f"<{self.destination}> ({DESTINATION})"
        self._allowed = {f"[walk] {item}", f"[turnto] {item}", f"[lookat] {item}",
                         f"[grab] {item}", f"[walk] {target}", f"[putback] {item} {target}"}

    def check_connection(self):
        """The imported local engine is available without a network endpoint."""
        return True

    def reset(self, environment: int):
        if type(environment) is not int or environment != 0:
            raise ValueError("The Evolving Graph backend provides only the authored kitchen (environment 0).")
        is_tray = self.destination == "tray"
        self._setup = {
            "nodes": [_node(ROOM, "kitchen", "Rooms"),
                      _node(TABLE, "kitchentable", "Furniture", "SURFACES"),
                      _node(ITEM, self.item, "Props", "GRABBABLE"),
                      _node(DESTINATION, self.destination, "Props" if is_tray else "Furniture", "SURFACES")],
            "edges": [_edge(i, "INSIDE", ROOM) for i in (TABLE, ITEM, DESTINATION)] + [_edge(ITEM, "ON", TABLE)],
        }
        if is_tray:
            self._setup["edges"].append(_edge(DESTINATION, "ON", TABLE))
        self._state = None
        self._executor = None

    def add_character(self, resource="Chars/Male1", initial_room="kitchen"):
        if self._setup is None or self._executor is not None:
            raise ValueError("Reset the scene before adding its single character.")
        if resource != "Chars/Male1" or initial_room != "kitchen":
            raise ValueError("The authored graph supports one Chars/Male1 character in the kitchen.")
        graph_dict = deepcopy(self._setup)
        graph_dict["nodes"].append(_node(CHARACTER, "character", "Characters", "PERSON"))
        graph_dict["edges"].append(_edge(CHARACTER, "INSIDE", ROOM))
        graph = EnvironmentGraph(graph_dict)
        self._executor = ScriptExecutor(graph, {}, char_index=0)
        self._state = EnvironmentState(graph, {}, instance_selection=True)

    def environment_graph(self):
        if self._setup is None:
            raise ValueError("Reset the authored scene before requesting its graph.")
        observed = self._setup if self._state is None else self._state.to_dict()
        return deepcopy(observed)

    def render_script(self, script: list[str]) -> tuple[bool, str]:
        if self._executor is None:
            raise ValueError("Add the character before executing a transfer.")
        if not isinstance(script, list) or not script:
            raise ValueError("Expected a nonempty list of character action lines.")
        for line in script:
            if not isinstance(line, str) or not line.startswith("<char0> "):
                raise ValueError("The authored graph accepts only commands for <char0>.")
            command = line[len("<char0> "):].strip().lower()
            if command not in self._allowed:
                raise ValueError("The command must use a supported action and its bound task entities.")
            # The engine owns all action checks, state transitions and retained executor_data.
            self._executor.info.messages.clear()
            success, self._state = self._executor.execute_one_step(
                read_script_from_list_string([command]), self._state)
            if not success:
                return False, self._executor.info.get_error_string()
        return True, "Evolving Graph executed the supplied action lines."
