"""Interpret tabletop plan statements against the symbolic verifier's scene."""

import ast
from copy import deepcopy
from dataclasses import dataclass

from verifier import tabletop


class InvalidProgram(ValueError):
    def __init__(self, message, line=None):
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class Statement:
    line: int
    kind: str
    name: str
    arguments: tuple
    recovery: tuple = ()


def _call(node, signatures):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise InvalidProgram("Expected a direct call to a listed primitive.", node.lineno)
    name = node.func.id
    if name not in signatures:
        raise InvalidProgram(f"Unsupported primitive: {name}.", node.lineno)
    parameters = signatures[name]
    if node.keywords or len(node.args) != len(parameters):
        raise InvalidProgram(f"{name} requires {len(parameters)} positional arguments.", node.lineno)
    values = []
    for arg, allowed in zip(node.args, parameters):
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str) or arg.value not in allowed:
            raise InvalidProgram(f"Expected a literal scene ID from {sorted(allowed)}.", node.lineno)
        values.append(arg.value)
    return name, tuple(values)


def _parse(program, transfer):
    if not isinstance(program, str) or len(program) > 8192:
        raise InvalidProgram("Expected a program of at most 8192 characters.")
    try:
        module = ast.parse(program, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise InvalidProgram(str(exc), getattr(exc, "lineno", None)) from exc
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise InvalidProgram("Expected exactly one function: def plan():")
    fn = module.body[0]
    args = fn.args
    if (fn.name != "plan" or fn.decorator_list or fn.returns or fn.type_comment
            or getattr(fn, "type_params", ()) or args.posonlyargs or args.args or args.kwonlyargs
            or args.vararg or args.kwarg):
        raise InvalidProgram("Expected an undecorated def plan(): with no arguments or annotations.", fn.lineno)
    if sum(isinstance(n, ast.stmt) for n in ast.walk(fn)) > 65:
        raise InvalidProgram("A plan may contain at most 64 statements.")

    item = {transfer.item_id}
    destination = {transfer.destination_id}
    actions = {"inspect": (item,), "pick": (item,), "place": (item, destination)}
    predicates = {"holding": (item,), "hand_empty": (), "reachable": (item | destination | {tabletop.TABLE},),
                  "on": (item, destination | {tabletop.TABLE})}

    def block(nodes):
        statements = []
        for node in nodes:
            if isinstance(node, ast.If) and not node.orelse and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
                name, values = _call(node.test.operand, predicates)
                statements.append(Statement(node.lineno, "guard", name, values, block(node.body)))
            elif isinstance(node, ast.Assert) and node.msg is None:
                name, values = _call(node.test, predicates)
                statements.append(Statement(node.lineno, "assert", name, values))
            elif isinstance(node, ast.Expr):
                name, values = _call(node.value, actions)
                statements.append(Statement(node.lineno, "action", name, values))
            else:
                raise InvalidProgram("Expected an action, assertion or 'if not predicate():' recovery block.", node.lineno)
        return tuple(statements)

    body = fn.body[1:] if ast.get_docstring(fn) is not None else fn.body
    return block(body)


def _evaluate(statement, scene, transfer):
    args = statement.arguments
    if statement.name == "hand_empty":
        return scene["arm"]["held"] is None
    if statement.name == "holding":
        return scene["arm"]["held"] == args[0]
    if statement.name == "reachable":
        return args[0] in scene["arm"]["reachable"]
    return scene[transfer.item]["on"] == args[1]


def check_program(program: str, bundle: dict) -> dict:
    """Validate the whole program, then simulate the path selected by its guards."""
    report = {"task_id": None, "status": "failed", "actions": [], "assertions": [],
              "errors": [], "goal_met": False, "final_state": None}
    if not isinstance(bundle, dict):
        report["errors"].append({"phase": "input", "message": "Expected a tabletop task bundle."})
        return report
    # With an empty trace, a goal-only failure means the verifier accepted the
    # task schema, fixed goal, and initial scene. Reference actions are ignored.
    initial = tabletop.verify_task({**bundle, "actions": []})
    report.update(task_id=initial["task_id"], final_state=initial["initial_state"])
    if any(error["phase"] != "goal" for error in initial["errors"]):
        report["errors"] = initial["errors"]
        return report
    scene = deepcopy(initial["initial_state"])
    transfer = tabletop._validate_scene(scene)
    try:
        statements = _parse(program, transfer)
    except InvalidProgram as exc:
        report["status"] = "invalid_program"
        report["errors"].append({"phase": "parse", "line": exc.line, "message": str(exc)})
        return report

    def run(block):
        for statement in block:
            if statement.kind == "action":
                action = {"action": statement.name, "object": statement.arguments[0]}
                if statement.name == "place":
                    action["target"] = statement.arguments[1]
                report["actions"].append(action)
                try:
                    tabletop._step(scene, action, transfer)
                except tabletop.RuleViolation as exc:
                    report["errors"].append({"phase": "action", "line": statement.line,
                                             "action_index": len(report["actions"]) - 1,
                                             "rule_id": exc.rule_id, "message": str(exc)})
                    return False
            else:
                value = _evaluate(statement, scene, transfer)
                entry = {"line": statement.line, "kind": statement.kind, "predicate": statement.name,
                         "arguments": list(statement.arguments), "value": value}
                report["assertions"].append(entry)
                if statement.kind == "guard":
                    entry["recovery_taken"] = not value
                    if not value and not run(statement.recovery):
                        return False
                elif not value:
                    report["errors"].append({"phase": "assertion", "line": statement.line,
                                             "message": f"Assertion {statement.name}{statement.arguments} was false."})
                    return False
        return True

    if run(statements):
        checked = tabletop.verify_task({**bundle, "actions": report["actions"]})
        report.update(status=checked["status"], goal_met=checked["goal_met"],
                      errors=checked["errors"], final_state=checked["final_state"])
    return report
