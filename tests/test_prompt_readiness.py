import io
import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from progprompt.resources import DEFAULT_DIRECTORY, RUNTIME_RESOURCES, check_prompts, run


ROOT = Path(__file__).resolve().parents[1]


class PromptReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        for resource in DEFAULT_DIRECTORY.iterdir():
            if resource.is_file():
                shutil.copyfile(resource, self.directory / resource.name)

    def edit_manifest(self, update):
        path = self.directory / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        update(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_active_roles_are_ready_with_explicit_runtime_bindings(self):
        report = check_prompts(self.directory)
        self.assertTrue(report["active_templates_ready"])
        self.assertEqual({row["file"] for row in report["active_templates"]}, set(RUNTIME_RESOURCES))
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
        self.assertEqual(report["issues"][0]["resource"], "manifest.json")

    def test_paths_cannot_escape_or_select_subdirectories(self):
        for path in ("../query.txt", "subdir/query.txt", "subdir\\query.txt", str(DEFAULT_DIRECTORY / "query.txt")):
            with self.subTest(path=path):
                self.edit_manifest(lambda manifest: manifest["templates"][2].update(file=path))
                self.assertFalse(check_prompts(self.directory)["active_templates_ready"])

    def test_exact_field_match_includes_runtime_binding(self):
        self.edit_manifest(lambda manifest: manifest["templates"][2].update(fields=["invented"]))
        (self.directory / "query.txt").write_text("$invented", encoding="utf-8")
        report = check_prompts(self.directory)
        self.assertFalse(report["active_templates_ready"])
        self.assertTrue(any("runtime handler" in issue["message"] for issue in report["issues"]))

    def test_empty_placeholder_and_source_records_do_not_imply_a_pipeline(self):
        report = check_prompts(self.directory)
        self.assertEqual(report["full_paper_pipeline"], "incomplete")
        self.assertEqual(report["placeholders"][0]["status"], "empty")
        self.assertIsNone(report["placeholders"][0]["runtime_handler"])
        self.assertTrue(all(row["status"] == "source_only" for row in report["source_records"]))
        (self.directory / "dominant_action_identification.txt").write_text("User supplied text.", encoding="utf-8")
        report = check_prompts(self.directory)
        self.assertEqual(report["placeholders"][0]["status"], "unconnected")
        self.assertEqual(report["full_paper_pipeline"], "incomplete")
        self.assertGreater(len(report["missing_components"]), 1)

    def test_run_prints_incomplete_report_without_a_model(self):
        out = io.StringIO()
        with patch("hf_client.generate_text", side_effect=AssertionError("Model should not load")), redirect_stdout(out):
            code = run(Namespace(directory=self.directory))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["full_paper_pipeline"], "incomplete")


if __name__ == "__main__":
    unittest.main()
