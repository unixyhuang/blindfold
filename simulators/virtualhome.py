"""Execute the bundled ordinary transfer tasks in a running VirtualHome instance."""

import json
import re
from pathlib import Path

from progprompt.cli import ROOT, TASKS, generate_plan
from progprompt.runtime import check_program
from simulators.virtualhome_client import UnityClient, VirtualHomeError
from verifier.tabletop import _validate_scene, verify_task


ITEM_CLASSES = {"apple": {"apple"}, "cup": {"cup", "mug"}}
DESTINATION_CLASSES = {"counter": {"kitchencounter"}, "tray": {"tray"}}
HOLDS = {"HOLDS_LH", "HOLDS_RH"}


def nodes_by_id(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError("Expected a complete VirtualHome graph with nodes and edges.")
    nodes = {}
    for node in graph["nodes"]:
        if (not isinstance(node, dict) or type(node.get("id")) is not int
                or not isinstance(node.get("class_name"), str) or node["id"] in nodes):
            raise ValueError("Graph nodes need unique integer IDs and class_name strings.")
        nodes[node["id"]] = node
    for edge in graph["edges"]:
        if (not isinstance(edge, dict) or type(edge.get("from_id")) is not int
                or type(edge.get("to_id")) is not int or not isinstance(edge.get("relation_type"), str)
                or edge["from_id"] not in nodes or edge["to_id"] not in nodes):
            raise ValueError("Graph edges must reference known node IDs and a relation_type.")
    return nodes


def _relation(edge, name):
    return edge["relation_type"].upper() == name


def bind_scene(bundle, graph, supplied=None):
    """Bind symbolic IDs to actual graph instances; ambiguous names require explicit IDs."""
    transfer = _validate_scene(bundle["scene"])
    nodes = nodes_by_id(graph)
    supplied = {} if supplied is None else supplied
    symbols = {transfer.item_id, transfer.destination_id, "table_1"}
    if (not isinstance(supplied, dict) or not supplied.keys() <= symbols
            or any(type(value) is not int or value not in nodes for value in supplied.values())):
        raise ValueError("Bindings must map this task's symbolic IDs to existing integer graph IDs.")
    result = dict(supplied)
    roles = ((transfer.item_id, ITEM_CLASSES[transfer.item]),
             (transfer.destination_id, DESTINATION_CLASSES[transfer.destination]))
    for symbol, classes in roles:
        candidates = sorted(node_id for node_id, node in nodes.items() if node["class_name"].lower() in classes)
        if symbol in result:
            if result[symbol] not in candidates:
                raise ValueError(f"Binding {symbol} requires class {sorted(classes)}, not {nodes[result[symbol]]['class_name']}.")
        elif len(candidates) == 1:
            result[symbol] = candidates[0]
        else:
            raise ValueError(f"Binding {symbol} is missing or ambiguous; candidate graph IDs: {candidates}. Supply --bindings.")
    if result[transfer.item_id] == result[transfer.destination_id]:
        raise ValueError("The item and its destination must be distinct graph nodes.")
    supports = sorted({edge["to_id"] for edge in graph["edges"]
                       if edge["from_id"] == result[transfer.item_id] and _relation(edge, "ON")})
    if len(supports) != 1 or supports[0] in {result[transfer.item_id], result[transfer.destination_id]}:
        raise ValueError("The item needs one distinct initial ON support, separate from its destination.")
    if "table_1" not in result:
        result["table_1"] = supports[0]
    if result["table_1"] not in supports:
        raise ValueError("The supplied initial support does not match the observed item ON relation.")
    if any(edge["relation_type"].upper() in HOLDS and edge["to_id"] == result[transfer.item_id]
           for edge in graph["edges"]):
        raise ValueError("The bundled initial scene requires an unheld item.")
    if transfer.destination == "tray":
        tray_supports = {edge["to_id"] for edge in graph["edges"]
                         if edge["from_id"] == result[transfer.destination_id] and _relation(edge, "ON")}
        if tray_supports != {result["table_1"]}:
            raise ValueError("The bundled cup task requires its tray on the same initial support as the cup.")
    return result


def compile_script(actions, graph, bindings):
    """Translate the small tabletop action interface, using graph IDs verbatim."""
    nodes = nodes_by_id(graph)

    def argument(symbol):
        node = nodes[bindings[symbol]]
        name = node["class_name"]
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise ValueError("A bound class_name is not a VirtualHome script identifier.")
        return f"<{name}> ({node['id']})"

    script = []
    for index, action in enumerate(actions):
        item = argument(action["object"])
        if action["action"] == "inspect":
            commands = [("walk", item), ("turnto", item), ("lookat", item)]
        elif action["action"] == "pick":
            commands = [("walk", item), ("grab", item)]
        elif action["action"] == "place":
            target = argument(action["target"])
            commands = [("walk", target), ("putback", f"{item} {target}")]
        else:
            raise ValueError("Only inspect, pick and place are supported by this transfer adapter.")
        script.extend({"action_index": index, "line": f"<char0> [{name}] {args}"} for name, args in commands)
    return script


def observe_goal(bundle, graph, bindings, character_id):
    """Use returned graph relations, independently of the symbolic plan verdict."""
    nodes = nodes_by_id(graph)
    item, destination = bundle["goal"]["on"]
    required = {bindings[item], bindings[destination], character_id}
    if not required <= nodes.keys():
        return {"status": "unknown", "checks": [{"rule": "missing_goal_nodes", "value": None}]}
    on = any(edge["from_id"] == bindings[item] and edge["to_id"] == bindings[destination]
             and _relation(edge, "ON") for edge in graph["edges"])
    empty = not any(edge["from_id"] == character_id and edge["relation_type"].upper() in HOLDS
                    for edge in graph["edges"])
    return {"status": "supported" if on and empty else "contradicted", "checks": [
        {"rule": "item_on_destination", "value": on, "from_id": bindings[item], "to_id": bindings[destination]},
        {"rule": "character_hands_empty", "value": empty, "character_id": character_id},
    ]}


def execute_transfer(bundle, plan, client, *, environment=0, supplied_bindings=None,
                     character="Chars/Male1", initial_room="kitchen"):
    """Run one already checked transfer and stop at the first rejected Unity command."""
    report = {"task_id": bundle["task_id"], "status": "not_run", "stage": "planning",
              "environment": environment, "planner": plan, "execution": [], "goal_met": None}
    if plan.get("status") != "passed":
        report["status"] = "invalid_plan"
        return report
    # A caller cannot obtain execution just by marking an arbitrary trace passed.
    checked = verify_task({**bundle, "actions": plan.get("actions")})
    if checked["status"] != "passed":
        report.update(status="invalid_plan", symbolic_recheck=checked)
        return report
    rejected = False
    try:
        report["stage"] = "connection"
        if not client.check_connection():
            raise VirtualHomeError("VirtualHome did not confirm the idle request.")
        report["stage"] = "scene_setup"
        client.reset(environment)
        protocol = getattr(client, "reset_protocol", None)
        if isinstance(protocol, str):
            report["reset_protocol"] = protocol
        client.add_character(character, initial_room=initial_room)
        before = client.environment_graph()
        nodes = nodes_by_id(before)
        characters = [node_id for node_id, node in nodes.items()
                      if node["class_name"].lower() == "character" or str(node.get("category", "")).lower() == "characters"]
        if len(characters) != 1:
            raise ValueError("Expected exactly one character after resetting and adding char0.")
        character_id, = characters
        if any(edge["from_id"] == character_id and edge["relation_type"].upper() in HOLDS for edge in before["edges"]):
            raise ValueError("The new character must start with both hands empty.")
        report.update(before_graph=before, character_id=character_id, stage="binding")
        bindings = bind_scene(bundle, before, supplied_bindings)
        script = compile_script(plan["actions"], before, bindings)
        report.update(bindings=bindings, script=script, stage="execution")
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
        observed = observe_goal(bundle, after, bindings, character_id)
        report.update(after_graph=after, observed_goal=observed,
                      goal_met={"supported": True, "contradicted": False, "unknown": None}[observed["status"]])
        report["status"] = "execution_failed" if rejected else {
            "supported": "passed", "contradicted": "failed", "unknown": "unknown"}[observed["status"]]
        report["stage"] = "complete"
    except (VirtualHomeError, ValueError, KeyError) as error:
        report.update(status="unavailable" if report["stage"] == "connection" else "error", error=str(error))
        # A timed-out render may already have changed the scene; it is never retried.
        if report["stage"] in {"execution", "observation"}:
            report["status"] = "execution_failed" if rejected else "unknown"
            try:
                report["after_graph"] = client.environment_graph()
                report["observed_goal"] = observe_goal(bundle, report["after_graph"], bindings, character_id)
            except (VirtualHomeError, ValueError, KeyError) as observation_error:
                report["observation_error"] = str(observation_error)
    return report


def add_arguments(parser):
    operations = parser.add_subparsers(dest="operation", required=True)
    inspect = operations.add_parser("inspect", help="Read a running VirtualHome graph and its object IDs.")
    inspect.add_argument("--environment", type=int, help="Explicitly reset to this scene before reading its graph.")
    inspect.add_argument("--output", type=Path, help="Save the graph JSON used to prepare bindings.")
    execute = operations.add_parser("run", help="Plan, check, execute and observe one bundled ordinary transfer.")
    execute.add_argument("--task", choices=sorted(TASKS), default="cup_to_counter")
    mode = execute.add_mutually_exclusive_group(required=True)
    mode.add_argument("--program", type=Path, help="Check a saved def plan() program before executing.")
    mode.add_argument("--model", type=Path, help="Generate a plan with local Hugging Face weights.")
    mode.add_argument("--recorded", action="store_true", help="Use the task's recorded reference actions.")
    execute.add_argument("--device", choices=["auto", "cpu"], default="auto")
    execute.add_argument("--max-new-tokens", type=int, default=256)
    execute.add_argument("--input-format", choices=["chat", "completion"], default="chat")
    execute.add_argument("--environment", type=int, default=0)
    execute.add_argument("--bindings", type=Path, help="JSON mapping symbolic IDs to Unity graph integer IDs.")
    execute.add_argument("--character", default="Chars/Male1")
    execute.add_argument("--initial-room", choices=["kitchen", "bedroom", "livingroom", "bathroom"], default="kitchen")
    execute.add_argument("--output-dir", type=Path, required=True, help="Empty directory for the run report and scene graphs.")
    for operation in (inspect, execute):
        operation.add_argument("--host", default="127.0.0.1")
        operation.add_argument("--port", type=int, default=8080)
        operation.add_argument("--timeout", type=float, default=30)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(args):
    client = UnityClient(args.host, args.port, args.timeout)
    if args.environment is not None and args.environment < 0:
        raise ValueError("--environment must be nonnegative.")
    if args.operation == "inspect":
        try:
            if not client.check_connection():
                raise VirtualHomeError("VirtualHome did not confirm the idle request.")
            if args.environment is not None:
                client.reset(args.environment)
            graph = client.environment_graph()
            nodes_by_id(graph)
            if args.output:
                _write(args.output, graph)
            print(json.dumps({"status": "connected", "graph": graph}, indent=2))
            return 0
        except (VirtualHomeError, ValueError) as error:
            print(json.dumps({"status": "unavailable", "error": str(error)}))
            return 2
    folder = args.output_dir
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Choose an empty --output-dir for each VirtualHome run.")
    supplied = json.loads(args.bindings.read_text(encoding="utf-8-sig")) if args.bindings else None
    bundle = json.loads((ROOT / "tasks" / TASKS[args.task]).read_text(encoding="utf-8"))
    if args.recorded:
        plan = {**verify_task(bundle), "actions": bundle["actions"], "source": "recorded_reference"}
    elif args.model:
        plan = generate_plan(bundle, args.model, device=args.device,
                             max_new_tokens=args.max_new_tokens, input_format=args.input_format)
    else:
        program = args.program.read_text(encoding="utf-8-sig")
        plan = check_program(program, bundle)
        plan.update(program=program, source="saved_program")
    report = execute_transfer(bundle, plan, client, environment=args.environment, supplied_bindings=supplied,
                              character=args.character, initial_room=args.initial_room)
    _write(folder / "report.json", report)
    for key in ("before_graph", "after_graph", "bindings"):
        if key in report:
            _write(folder / (key + ".json"), report[key])
    if "script" in report:
        (folder / "script.txt").write_text("\n".join(step["line"] for step in report["script"]) + "\n", encoding="utf-8")
    if "program" in plan:
        (folder / "plan.py").write_text(plan["program"], encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] == "passed":
        return 0
    return 1 if report["status"] in {"failed", "execution_failed", "unknown"} else 2
