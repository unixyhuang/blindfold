"""Write a task-by-task Chinese report from completed generated-plan checks."""

from collections import Counter
from html import escape
import json
from pathlib import Path


LABELS = {
    "supported": "终态有符号证据",
    "unknown": "证据不足",
    "contradicted": "与动作规则或终态目标矛盾",
    "invalid_program": "程序不符合接口",
}
PRECONDITIONS = {
    "no_prior_find": "操作对象之前没有通过 find 引入",
    "hand_occupied": "夹爪中已有物体，不能再次拾取",
    "empty_hand": "夹爪为空，无法执行这个动作",
    "closed_container": "容器已明确关闭，不能向其中放置物体",
    "containment_cycle": "放置动作会形成循环容纳关系",
}
PROGRAM_ERRORS = {
    "invalid_program_text": "程序正文缺失或超出长度上限",
    "syntax_error": "Python 语法无法解析",
    "invalid_function": "输出必须包含一个无参数的 def plan() 函数",
    "too_many_statements": "程序超出语句数上限",
    "invalid_call": "此处需要直接调用已声明的动作或谓词",
    "unsupported_primitive": "调用了接口未声明的动作或谓词",
    "unsupported_statement": "使用了计划语言不支持的语句",
    "wrong_arguments": "实参数量或传参形式不符合动作接口",
    "nonliteral_argument": "参数须为字符串字面量",
    "object_outside_inventory": "引用的物体类型不在本次提示的清单内",
    "unsupported_object_type": "引用的物体类型超出 verifier 的词表",
    "unsupported_liquid": "液体名称不在接口词表内",
    "no_generated_steps": "生成程序没有产生可供核对的动作",
}


def _cell(value):
    text = " ".join(str(value).split())
    text = escape(text, quote=False)
    for char in "\\|`*[]":
        text = text.replace(char, f"&#{ord(char)};")
    return text


def _goal_detail(check):
    item = check["objectType"]
    field = check["predicate"]
    expected = check["expected"]
    if field == "liquidReceived":
        source = expected.get("source")
        origin = f"由 {source} 转移" if source else "发生转移"
        relation = "内部" if expected["relation"] == "into" else "表面"
        return f"{expected['liquid']} {origin}到 {item} {relation}"
    value = json.dumps(expected, ensure_ascii=False, separators=(", ", ": "))
    return f"{item}.{field} = {value}"


def _step_evidence(steps, index):
    if isinstance(index, int) and 0 <= index < len(steps):
        return f"第 {index + 1} 步 {steps[index]}"
    return ""


def _row_explanations(row):
    details = []
    steps = row.get("generated_steps", [])
    program = row.get("program", "").splitlines()
    checks = {(c["objectType"], c["predicate"]): c for c in row.get("checks", []) if c["status"] != "supported"}
    for issue in row.get("issues", []):
        rule = issue.get("rule")
        check = checks.pop((issue.get("objectType"), issue.get("predicate")), None)
        if check:
            goal = _goal_detail(check)
            evidence = _step_evidence(steps, check.get("evidence_step_index"))
            if rule == "missing_generated_pour":
                msg = f"程序没有生成 pour 动作，缺少实现“{goal}”的步骤"
            elif rule == "unobserved_liquid_transfer":
                pours = [str(i + 1) for i, step in enumerate(steps) if step == "pour"]
                msg = f"第 {'、'.join(pours)} 步发生倾倒，缺少“{goal}”的转移观测"
            elif rule == "direct_destination_differs_ancestry_unknown":
                msg = f"放置目的地是 {check['recorded_destination']}，完整父容器链未知，无法确认 {goal}"
            elif check["status"] == "contradicted":
                msg = f"生成步骤建立的状态与 {goal} 矛盾"
            else:
                msg = f"生成步骤未能建立 {goal}"
            if evidence:
                msg += f"（相关动作：{evidence}）"
        elif rule in PRECONDITIONS:
            position = _step_evidence(steps, issue.get("step_index"))
            msg = f"{position}：{PRECONDITIONS[rule]}" if position else PRECONDITIONS[rule]
        elif rule in PROGRAM_ERRORS:
            msg = PROGRAM_ERRORS[rule]
            line = issue.get("line")
            if isinstance(line, int) and 1 <= line <= len(program):
                fragment = program[line - 1].strip()
                if fragment:
                    msg += f"（程序第 {line} 行：{fragment[:150]}）"
            if issue.get("message") and rule in {"syntax_error", "object_outside_inventory", "unsupported_primitive"}:
                msg += f"。{issue['message']}"
        elif rule in {"assertion_false", "unknown_predicate"}:
            event = next((e for e in reversed(row.get("assertions", [])) if e["line"] == issue.get("line")), None)
            msg = "断言在当前符号状态为假" if rule == "assertion_false" else "当前状态不足以判断谓词，无法继续选择执行路径"
            if event:
                args = ", ".join(repr(a) for a in event["arguments"])
                expression = event.get("expression", f"{event['predicate']}({args})")
                msg += f"（程序第 {event['line']} 行：{expression}）"
        elif rule == "scene_object_unavailable":
            msg = "生成计划未能在本次清单中找到所需对象"
            if issue.get("message"):
                msg += f"。{issue['message']}"
        elif rule == "liquid_outcome_unobserved":
            # A goal-specific transfer explanation is more informative than this trace note.
            continue
        elif rule == "missing_goal_annotation":
            msg = "任务缺少终态标注"
        else:
            msg = issue.get("message") or str(rule)
        if msg not in details:
            details.append(msg)
    for check in checks.values():
        label = "与目标矛盾" if check["status"] == "contradicted" else "证据不足"
        details.append(f"{_goal_detail(check)}：{label}")
    if not details:
        details.extend(reason["message"] for reason in row.get("reasons", []) if reason.get("message"))
    missing = row.get("inventory_missing_mentions", [])
    if missing:
        details.append("任务涉及但提示清单未列出的类型：" + "、".join(str(item) for item in missing))
    return details


def write_reports(folder, results, summary):
    """Write failures.md; list every result whose generated plan was not supported."""
    counts = Counter(r["status"] for r in results)
    other = [r for r in results if r["status"] != "supported"]
    lines = ["# 生成计划核验报告", "",
             f"共核验 {len(results)} 条计划，涉及 {summary['scenes']} 个场景。"
             f"其中 {counts['supported']} 条的终态获得符号步骤支持，{len(other)} 条列于下表。",
             "", "| 判定 | 任务数 |", "| --- | ---: |"]
    for key in dict.fromkeys([*LABELS, *sorted(counts)]):
        lines.append(f"| {_cell(LABELS.get(key, key))} | {counts[key]} |")
    lines.extend(["", "动作序号从 1 开始。证据不足表示现有步骤不能确认目标；物体缺口仅描述本次提示使用的清单。", "",
                  "| 任务 ID | 场景 | 指令 | 判定 | 具体原因 |", "| --- | --- | --- | --- | --- |"])
    for row in other:
        cells = [_cell(row["task_id"]), _cell(row["scene_name"]), _cell(row.get("instruction", "")),
                 _cell(LABELS.get(row["status"], row["status"]))]
        cells.append("<br>".join(_cell(reason) for reason in _row_explanations(row)))
        lines.append("| " + " | ".join(cells) + " |")
    path = Path(folder) / "failures.md"
    pending = path.with_suffix(".md.tmp")
    pending.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pending.replace(path)
