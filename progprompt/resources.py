"""Read-only checks of prompt resources and the implemented workflow scope."""

import hashlib
import json
import re
from pathlib import Path
from string import Template


DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "prompts" / "progprompt"
ATTACK_HANDLER = "progprompt.attack.render_stage_prompt"
RUNTIME_RESOURCES = {
    "header.txt": ("literal", (), ["render", "generate"], ["progprompt.cli.render_prompt"]),
    "demonstrations.txt": ("literal", (), ["render", "generate"], ["progprompt.cli.render_prompt"]),
    "query.txt": ("dollar", ("objects", "items", "destinations", "scene", "instruction", "task_function"),
                  ["render", "generate"], ["progprompt.cli.render_prompt"]),
    "tabletop_chat.txt": ("dollar", ("planning_context",), ["render", "generate"], ["progprompt.cli.render_chat_prompt"]),
    "task_planning.txt": ("dollar", ("scene", "objects", "instruction"),
                          ["benchmark"], ["progprompt.benchmark.render_instruction"]),
    "tabletop_chain_fusion.txt": ("double_braces", ("merge_record_json",),
                                  ["fuse"], ["progprompt.tabletop_merge.render_merge_prompt"]),
    "verifier_feedback.txt": ("double_braces", ("feedback_record_json",),
                              ["feedback"], ["progprompt.feedback.render_feedback"]),
    "chain_command_transformer.txt": ("double_braces", ("chain_context_json",),
                                      ["attack"], [ATTACK_HANDLER]),
    "chain_sanitization.txt": ("double_braces", ("paper_prompt", "chain_context_json"),
                               ["attack"], [ATTACK_HANDLER]),
    "chain_dominant_action.txt": ("double_braces", ("paper_prompt", "chain_context_json"),
                                  ["attack"], [ATTACK_HANDLER]),
    "chain_cover_branch.txt": ("double_braces", ("paper_prompt", "chain_context_json"),
                               ["attack"], [ATTACK_HANDLER]),
    "chain_fusion_runtime.txt": ("double_braces", ("paper_prompt", "chain_context_json"),
                                 ["attack"], [ATTACK_HANDLER]),
    "chain_repair.txt": ("double_braces", ("chain_context_json",),
                         ["attack"], [ATTACK_HANDLER]),
}
PAPER_PROMPTS = (
    "command_sanitization.txt", "dominant_action_identification.txt",
    "cover_branch_generation.txt", "chain_fusion.txt",
)
# Supplied paper text -> (stage name, runtime wrapper template).
PAPER_RUNTIME = {
    "command_sanitization.txt": ("command_sanitization", "chain_sanitization.txt"),
    "dominant_action_identification.txt": ("dominant_action_identification", "chain_dominant_action.txt"),
    "cover_branch_generation.txt": ("cover_branch_generation", "chain_cover_branch.txt"),
    "chain_fusion.txt": ("chain_fusion", "chain_fusion_runtime.txt"),
}
CHAIN_TEMPLATES = (
    "chain_command_transformer.txt", "chain_sanitization.txt", "chain_dominant_action.txt",
    "chain_cover_branch.txt", "chain_fusion_runtime.txt", "chain_repair.txt",
)
SOURCE_RECORDS = ("README.md",)
_BRACES = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _resource(directory, name):
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        raise ValueError("Resource paths must name a file directly in the prompt directory.")
    path = (directory / name).resolve()
    if path.parent != directory or not path.is_file():
        raise ValueError("Resource must be an existing file in the prompt directory.")
    return path.read_text(encoding="utf-8-sig")


def _resource_bytes(directory, name):
    _resource(directory, name)
    return (directory / name).read_bytes()


def _fields(body, format_name):
    dollar = set()
    for match in Template.pattern.finditer(body):
        if match.group("invalid") is not None:
            raise ValueError("Malformed dollar placeholder.")
        name = match.group("named") or match.group("braced")
        if name:
            dollar.add(name)
    brace_occurrences = _BRACES.findall(body)
    braces = set(brace_occurrences)
    remainder = _BRACES.sub("", body)
    # A lone closing brace may occur in a JSON example; an opening pair cannot.
    if "{{" in remainder:
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
        if len(brace_occurrences) != len(braces):
            raise ValueError("Double-brace fields must each occur exactly once.")
        return braces
    raise ValueError("Unsupported template format.")


def check_prompts(directory=None):
    """Check files and bindings without running prompts or loading a model."""
    directory = Path(directory or DEFAULT_DIRECTORY).resolve()
    report = {
        "status": "partial", "active_templates_ready": False,
        "active_templates": [], "paper_prompts": [], "paper_prompt_files_ready": False,
        "paper_prompt_runtime_ready": False, "chain_templates_ready": False,
        "chain_pipeline": "not_implemented",
        "source_records": [],
        "full_paper_pipeline": "partial", "missing_components": [
            {"component": "target_embodied_llm_query", "status": "not_implemented"},
            {"component": "paper_simulator_integration", "status": "partial",
             "detail": "Bundled VirtualHome Evolving Graph execution is implemented; Unity assets and the real robot arm are not."},
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
    ready_templates = {row["file"] for row in report["active_templates"] if row["status"] == "ready"}
    report["chain_templates_ready"] = set(CHAIN_TEMPLATES) <= ready_templates

    paper_prompts = manifest.get("paper_prompts")
    if not isinstance(paper_prompts, list):
        issue("manifest.json", "paper_prompts must be an array.")
        paper_prompts = []
    paper_names = set()
    for entry in paper_prompts:
        name = entry.get("file") if isinstance(entry, dict) else None
        row = {"file": name, "status": "invalid", "runtime_handler": None,
               "runtime_template": None,
               "manifest_status": entry.get("status") if isinstance(entry, dict) else None}
        report["paper_prompts"].append(row)
        try:
            if not isinstance(name, str) or name in paper_names:
                raise ValueError("Paper prompt names must be unique strings.")
            paper_names.add(name)
            body = _resource(directory, name)
            if name not in PAPER_PROMPTS:
                raise ValueError("Unknown paper prompt resource; expected one of the four declared .txt assets.")
            row.update(role=entry.get("role"), paper_section=entry.get("paper_section"),
                       print_page=entry.get("print_page"), pdf_page=entry.get("pdf_page"))
            if not body.strip():
                row["status"] = "empty"
                issue(name, "Paper prompt file is empty; source text is missing.")
                continue
            if row["manifest_status"] != "provided":
                raise ValueError("Paper prompt manifest status must be provided for a nonempty source asset.")
            if not isinstance(row["role"], str) or not row["role"].strip():
                raise ValueError("Paper prompt must declare its source role.")
            expected_digest = entry.get("source_sha256")
            digest = hashlib.sha256(_resource_bytes(directory, name)).hexdigest()
            if expected_digest != digest:
                raise ValueError("Supplied paper prompt body does not match its recorded digest.")
            stage, runtime_template = PAPER_RUNTIME[name]
            if entry.get("runtime_template") != runtime_template:
                raise ValueError("Paper prompt must reference its declared runtime template.")
            if entry.get("runtime_handler") != ATTACK_HANDLER:
                raise ValueError("Paper prompt must declare the attack runtime handler.")
            wrapper = _resource(directory, runtime_template)
            if wrapper.count("{{paper_prompt}}") != 1:
                raise ValueError("Runtime template must embed the paper prompt exactly once.")
            if runtime_template not in RUNTIME_RESOURCES:
                raise ValueError("Runtime template has no registered handler.")
            row.update(status="wired", runtime_handler=ATTACK_HANDLER,
                       runtime_template=runtime_template, stage=stage)
        except (OSError, ValueError, UnicodeError) as exc:
            row["error"] = str(exc)
            issue(name, str(exc))
    for name in set(PAPER_PROMPTS) - paper_names:
        issue(name, "Expected paper prompt asset is missing from the manifest.")
    report["paper_prompt_files_ready"] = (
        paper_names == set(PAPER_PROMPTS)
        and len(paper_prompts) == len(PAPER_PROMPTS)
        and all(row["status"] in ("provided", "wired") for row in report["paper_prompts"])
    )
    report["paper_prompt_runtime_ready"] = (
        paper_names == set(PAPER_PROMPTS)
        and all(row["status"] == "wired" and row["runtime_handler"] == ATTACK_HANDLER
                for row in report["paper_prompts"])
    )
    if report["paper_prompt_runtime_ready"] and report["chain_templates_ready"]:
        report["chain_pipeline"] = "ready"

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
    if report["chain_pipeline"] != "ready":
        issue("chain_pipeline",
              "The attack chain prompt stages are not all wired; the pipeline reports itself incomplete.")
    return report


def run(args):
    report = check_prompts(getattr(args, "directory", None))
    print(json.dumps(report, indent=2))
    return 1 if report["full_paper_pipeline"] != "ready" else 0
