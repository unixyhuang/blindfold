import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import patch

from progprompt.cli import ROOT, render_prompt, run


class PromptPipelineTests(unittest.TestCase):
    def test_target_uses_scene_and_instruction_only(self):
        bundle = json.loads((ROOT / "tasks/apple_to_counter.json").read_text())
        rendered = render_prompt(bundle)
        bundle.update(actions=["solution sentinel"], goal={"private": "goal sentinel"})
        self.assertEqual(render_prompt(bundle), rendered)
        self.assertIn("# Instruction: Place the apple on the kitchen counter.", rendered)
        self.assertIn('objects = ["apple_1", "counter_1", "table_1"]', rendered)
        self.assertTrue(rendered.endswith("def place_the_apple_on_the_kitchen_counter():\n    "))

    def test_model_continuation_reaches_checker(self):
        args = Namespace(operation="generate", task="apple_to_counter", model="checkpoint",
                         device="cpu", max_new_tokens=64, save_program=None)
        for continuation, expected in [
            ('if not holding("apple_1"):\n        pick("apple_1")\n'
             '    place("apple_1", "counter_1")\n\ndef other_task():', "passed"),
            ('place("apple_1", "counter_1")', "failed"),
            ('some explanation instead of code', "invalid_program"),
        ]:
            with self.subTest(expected=expected):
                out = io.StringIO()
                with patch("hf_client.generate_text", return_value=continuation) as model, redirect_stdout(out):
                    code = run(args)
                report = json.loads(out.getvalue())
                self.assertTrue(model.call_args.kwargs["completion"])
                self.assertEqual(report["source"], "model_generated")
                self.assertEqual(report["status"], expected)
                self.assertEqual(code == 0, expected == "passed")
