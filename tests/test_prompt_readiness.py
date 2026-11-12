import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from progprompt.resources import PAPER_PROMPTS, RUNTIME_RESOURCES, check_prompts, run


ROOT = Path(__file__).resolve().parents[1]


class PromptReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # Isolated fixtures never copy user-authored paper source text.
        templates = [
            {"file": "header.txt", "format": "literal", "fields": []},
            {"file": "demonstrations.txt", "format": "literal", "fields": []},
            {"file": "query.txt", "format": "dollar", "fields": [
                "objects", "items", "destinations", "scene", "instruction", "task_function"]},
            {"file": "task_planning.txt", "format": "dollar", "fields": ["scene", "objects", "instruction"]},
            {"file": "tabletop_chat.txt", "format": "dollar", "fields": ["planning_context"]},
            {"file": "tabletop_chain_fusion.txt", "format": "double_braces", "fields": ["merge_record_json"]},
            {"file": "verifier_feedback.txt", "format": "double_braces", "fields": ["feedback_record_json"]},
        ]
        for entry in templates:
            if entry["format"] == "dollar":
                body = " ".join("$" + field for field in entry["fields"])
            elif entry["format"] == "double_braces":
                body = " ".join("{{" + field + "}}" for field in entry["fields"])
            else:
                body = "Ordinary tabletop resource fixture."
            (self.directory / entry["file"]).write_text(body, encoding="utf-8")
        paper_prompts = []
        for name in PAPER_PROMPTS:
            (self.directory / name).write_text("Source asset fixture.", encoding="utf-8")
            paper_prompts.append({"file": name, "role": Path(name).stem, "status": "provided",
                                  "paper_section": "5", "print_page": 1061, "pdf_page": 5})
        (self.directory / "README.md").write_text("Source index fixture.", encoding="utf-8")
        (self.directory / "manifest.json").write_text(json.dumps({
            "artifact_version": "1.0", "framework": "ProgPrompt", "templates": templates,
            "paper_prompts": paper_prompts, "source_records": ["README.md"],
        }), encoding="utf-8")

    def edit_manifest(self, update):
        path = self.directory / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        update(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_active_roles_are_ready_with_explicit_runtime_bindings(self):
        report = check_prompts(self.directory)
        self.assertTrue(report["active_templates_ready"])
        self.assertEqual({row["file"] for row in report["active_templates"]}, set(RUNTIME_RESOURCES))
        self.assertNotIn("chain_fusion.txt", RUNTIME_RESOURCES)
        for row in report["active_templates"]:
            self.assertEqual(row["status"], "ready")
            self.assertTrue(row["entrypoints"])
            self.assertTrue(row["handlers"])

    def test_missing_empty_and_malformed_active_resources_fail(self):
        cases = {
            "missing": None,
            "empty": " \n",
            "undeclared": "$scene $unknown",
            "malformed": "${scene",
            "wrong_format": "{{scene}}",
        }
        path = self.directory / "query.txt"
        for label, body in cases.items():
            with self.subTest(label=label):
                if body is None:
                    path.unlink()
                else:
                    path.write_text(body, encoding="utf-8")
                report = check_prompts(self.directory)
                self.assertFalse(report["active_templates_ready"])
                row = next(row for row in report["active_templates"] if row["file"] == "query.txt")
                self.assertEqual(row["status"], "invalid")

    def test_malformed_manifest_and_omitted_runtime_template_fail(self):
        self.edit_manifest(lambda manifest: manifest["templates"].pop())
        self.assertFalse(check_prompts(self.directory)["active_templates_ready"])
        (self.directory / "manifest.json").write_text("{", encoding="utf-8")
        report = check_prompts(self.directory)
        self.assertFalse(report["active_templates_ready"])
        self.assertFalse(report["paper_prompt_files_ready"])
        self.assertEqual(report["issues"][0]["resource"], "manifest.json")

    def test_paths_cannot_escape_or_select_subdirectories(self):
        for path in ("../query.txt", "subdir/query.txt", "subdir\\query.txt", str(self.directory / "query.txt")):
            with self.subTest(path=path):
                self.edit_manifest(lambda manifest: manifest["templates"][2].update(file=path))
                self.assertFalse(check_prompts(self.directory)["active_templates_ready"])

    def test_exact_field_match_includes_runtime_binding(self):
        self.edit_manifest(lambda manifest: manifest["templates"][2].update(fields=["invented"]))
        (self.directory / "query.txt").write_text("$invented", encoding="utf-8")
        report = check_prompts(self.directory)
        self.assertFalse(report["active_templates_ready"])
        self.assertTrue(any("runtime handler" in issue["message"] for issue in report["issues"]))

    def test_provided_paper_sources_are_not_runtime_templates(self):
        # Template-looking source text remains opaque and is never substituted.
        (self.directory / "chain_fusion.txt").write_text("Source text: ${unclosed {{source only.", encoding="utf-8")
        report = check_prompts(self.directory)
        self.assertTrue(report["active_templates_ready"])
        self.assertTrue(report["paper_prompt_files_ready"])
        self.assertNotIn("placeholders", report)
        self.assertEqual(report["full_paper_pipeline"], "incomplete")
        self.assertGreater(len(report["missing_components"]), 1)
        self.assertEqual({row["file"] for row in report["paper_prompts"]}, set(PAPER_PROMPTS))
        for row in report["paper_prompts"]:
            self.assertEqual(row["status"], "provided")
            self.assertEqual(row["manifest_status"], "provided")
            self.assertIsNone(row["runtime_handler"])
        self.assertEqual(report["source_records"], [{"file": "README.md", "status": "source_only", "runtime_handler": None}])

    def test_missing_and_empty_paper_assets_are_explicit(self):
        name = "dominant_action_identification.txt"
        path = self.directory / name
        path.write_text(" \n", encoding="utf-8")
        report = check_prompts(self.directory)
        self.assertFalse(report["paper_prompt_files_ready"])
        row = next(row for row in report["paper_prompts"] if row["file"] == name)
        self.assertEqual(row["status"], "empty")
        self.assertTrue(any("source text is missing" in issue["message"] for issue in report["issues"]))
        path.unlink()
        report = check_prompts(self.directory)
        self.assertFalse(report["paper_prompt_files_ready"])
        self.assertEqual(next(row for row in report["paper_prompts"] if row["file"] == name)["status"], "invalid")
        self.assertEqual(report["full_paper_pipeline"], "incomplete")

    def test_paper_manifest_requires_all_assets_and_provided_status(self):
        self.edit_manifest(lambda manifest: manifest["paper_prompts"][0].update(status="unfilled"))
        report = check_prompts(self.directory)
        self.assertFalse(report["paper_prompt_files_ready"])
        self.assertEqual(report["paper_prompts"][0]["status"], "invalid")
        self.edit_manifest(lambda manifest: manifest["paper_prompts"].pop())
        report = check_prompts(self.directory)
        self.assertFalse(report["paper_prompt_files_ready"])
        self.assertTrue(any("missing from the manifest" in issue["message"] for issue in report["issues"]))

    def test_paper_asset_paths_cannot_escape(self):
        self.edit_manifest(lambda manifest: manifest["paper_prompts"][0].update(file="../command_sanitization.txt"))
        report = check_prompts(self.directory)
        self.assertFalse(report["paper_prompt_files_ready"])
        self.assertIn("directly in the prompt directory", report["paper_prompts"][0]["error"])

    def test_tabletop_merge_requires_the_input_field(self):
        cases = (("Missing input field.", "fields do not match"),
                 ("{{merge_record_json}} {{merge_record_json}}", "exactly once"))
        for body, error in cases:
            with self.subTest(body=body):
                (self.directory / "tabletop_chain_fusion.txt").write_text(body, encoding="utf-8")
                report = check_prompts(self.directory)
                self.assertFalse(report["active_templates_ready"])
                row = next(row for row in report["active_templates"] if row["file"] == "tabletop_chain_fusion.txt")
                self.assertIn(error, row["error"])

    def test_run_prints_incomplete_report_without_a_model(self):
        out = io.StringIO()
        with patch("hf_client.generate_text", side_effect=AssertionError("Model should not load")), redirect_stdout(out):
            code = run(Namespace(directory=self.directory))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["full_paper_pipeline"], "incomplete")


if __name__ == "__main__":
    unittest.main()
