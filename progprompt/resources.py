"""Read-only checks of prompt resources and the implemented workflow scope."""

import json
import re
from pathlib import Path
from string import Template


DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "prompts" / "progprompt"
RUNTIME_RESOURCES = {
    "header.txt": ("literal", (), ["render", "generate"], ["progprompt.cli.render_prompt"]),
    "demonstrations.txt": ("literal", (), ["render", "generate"], ["progprompt.cli.render_prompt"]),
    "query.txt": ("dollar", ("objects", "items", "destinations", "scene", "instruction", "task_function"),
                  ["render", "generate"], ["progprompt.cli.render_prompt"]),
    "task_planning.txt": ("dollar", ("scene", "objects", "instruction"),
                          ["benchmark"], ["progprompt.benchmark.render_instruction"]),
    "chain_fusion.txt": ("double_braces", ("merge_record_json",),
                         ["fuse"], ["progprompt.tabletop_merge.render_merge_prompt"]),
    "verifier_feedback.txt": ("double_braces", ("feedback_record_json",),
                              ["feedback"], ["progprompt.feedback.render_feedback"]),
}
SOURCE_RECORDS = (
    "command_sanitization.md", "dominant_action_identification.md", "cover_branch_generation.md",
)
_BRACES = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _resource(directory, name):
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        raise ValueError("Resource paths must name a file directly in the prompt directory.")
    path = (directory / name).resolve()
    if path.parent != directory or not path.is_file():
        raise ValueError("Resource must be an existing file in the prompt directory.")
    return path.read_text(encoding="utf-8-sig")


def _fields(body, format_name):
    dollar = set()
    for match in Template.pattern.finditer(body):
        if match.group("invalid") is not None:
            raise ValueError("Malformed dollar placeholder.")
        name = match.group("named") or match.group("braced")
        if name:
            dollar.add(name)
    braces = set(_BRACES.findall(body))
    remainder = _BRACES.sub("", body)
    if "{{" in remainder or "}}" in remainder:
        raise ValueError("Malformed double-brace placeholder.")
    if format_name == "literal":
        if dollar or braces:
            raise ValueError("Literal resources must not declare substitution fields.")
        return set()
    if format_name == "dollar":
        if braces:
            raise ValueError("Dollar templates contain a double-brace placeholder.")
        return dollar
    if format_name == "double_braces":
        if dollar:
            raise ValueError("Double-brace templates contain a dollar placeholder.")
        return braces
    raise ValueError("Unsupported template format.")


def check_prompts(directory=None):
    """Check files and bindings without running prompts or loading a model.

    Template readiness describes the released individual commands only. The
    missing original-paper implementations keep the full pipeline incomplete,
    including when all template files are present and nonempty.
    """
    directory = Path(directory or DEFAULT_DIRECTORY).resolve()
    report = {
        "status": "incomplete", "active_templates_ready": False,
        "active_templates": [], "placeholders": [], "source_records": [],
        "full_paper_pipeline": "incomplete", "missing_components": [
            {"component": "command_sanitization", "status": "not_implemented"},
            {"component": "dominant_action_identification", "status": "not_implemented"},
            {"component": "cover_branch_generation", "status": "not_implemented"},
            {"component": "paper_planner_verifier_loop", "status": "not_implemented"},
            {"component": "paper_simulator_integration", "status": "not_implemented"},
        ], "issues": [],
    }

    def issue(resource, message):
        report["issues"].append({"resource": resource, "message": message})

    try:
        manifest = json.loads(_resource(directory, "manifest.json"))
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be a JSON object.")
    except (OSError, ValueError, UnicodeError) as exc:
        issue("manifest.json", str(exc))
        return report

    templates = manifest.get("templates")
    if not isinstance(templates, list):
        issue("manifest.json", "templates must be an array.")
        templates = []
    seen = set()
    for entry in templates:
        name = entry.get("file") if isinstance(entry, dict) else None
        row = {"file": name, "status": "invalid", "entrypoints": [], "handlers": []}
        report["active_templates"].append(row)
        try:
            if not isinstance(name, str) or name in seen:
                raise ValueError("Template names must be unique strings.")
            seen.add(name)
            body = _resource(directory, name)
            if not body.strip():
                raise ValueError("Active template is empty.")
            fields = entry.get("fields")
            if (not isinstance(fields, list) or any(not isinstance(field, str) for field in fields)
                    or len(fields) != len(set(fields))):
                raise ValueError("fields must be an array of unique field names.")
            actual = _fields(body, entry.get("format"))
            row["fields"] = sorted(actual)
            if actual != set(fields):
                raise ValueError("Template fields do not match the manifest declaration.")
            binding = RUNTIME_RESOURCES.get(name)
            if binding is None:
                raise ValueError("No known runtime handler is registered for this resource.")
            format_name, expected, entrypoints, handlers = binding
            row.update(entrypoints=entrypoints, handlers=handlers)
            if entry.get("format") != format_name or actual != set(expected):
                raise ValueError("Template fields or format do not match the runtime handler.")
            row["status"] = "ready"
        except (OSError, ValueError, UnicodeError) as exc:
            row["error"] = str(exc)
            issue(name, str(exc))
    for name in RUNTIME_RESOURCES.keys() - seen:
        issue(name, "Runtime template is missing from the manifest.")
    report["active_templates_ready"] = (
        seen == set(RUNTIME_RESOURCES)
        and len(templates) == len(RUNTIME_RESOURCES)
        and all(row["status"] == "ready" for row in report["active_templates"])
    )

    placeholders = manifest.get("placeholders")
    if not isinstance(placeholders, list):
        issue("manifest.json", "placeholders must be an array.")
        placeholders = []
    placeholder_names = set()
    for entry in placeholders:
        name = entry.get("file") if isinstance(entry, dict) else None
        row = {"file": name, "status": "invalid", "runtime_handler": None}
        report["placeholders"].append(row)
        try:
            if not isinstance(name, str) or name in placeholder_names:
                raise ValueError("Placeholder names must be unique strings.")
            placeholder_names.add(name)
            body = _resource(directory, name)
            row.update(status="empty" if not body.strip() else "unconnected",
                       manifest_status=entry.get("status"), source_record=entry.get("source_record"))
            issue(name, "Placeholder has no runtime implementation; adding text alone does not connect the paper workflow.")
        except (OSError, ValueError, UnicodeError) as exc:
            row["error"] = str(exc)
            issue(name, str(exc))
    if "dominant_action_identification.txt" not in placeholder_names:
        issue("dominant_action_identification.txt", "Expected paper placeholder is missing from the manifest.")

    sources = manifest.get("source_records")
    if not isinstance(sources, list):
        issue("manifest.json", "source_records must be an array.")
        sources = []
    source_names = set()
    for name in sources:
        row = {"file": name, "status": "invalid", "runtime_handler": None}
        report["source_records"].append(row)
        try:
            if not isinstance(name, str) or name in source_names:
                raise ValueError("Source record names must be unique strings.")
            source_names.add(name)
            if not _resource(directory, name).strip():
                raise ValueError("Source record is empty.")
            row["status"] = "source_only"
        except (OSError, ValueError, UnicodeError) as exc:
            row["error"] = str(exc)
            issue(name, str(exc))
    for name in set(SOURCE_RECORDS) - source_names:
        issue(name, "Expected paper source record is missing from the manifest.")
    issue("full_paper_pipeline", "Released planning, feedback and merge commands are separate; the full paper workflow is not implemented.")
    return report


def run(args):
    report = check_prompts(getattr(args, "directory", None))
    print(json.dumps(report, indent=2))
    return 1 if report["full_paper_pipeline"] != "ready" else 0
