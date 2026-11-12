"""Training-free generation exploitation contracts."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace

import hf_client
from progprompt.training_free import (
    DEFAULT_PROFILES,
    Profile,
    RefusalError,
    generate_without_refusal,
    refusal_reason,
)


class FakeGenerator:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generate_many(self, prompts, **kwargs):
        self.calls.append({"prompts": list(prompts), **kwargs})
        if not self.answers:
            raise AssertionError("No fake answers left.")
        return [self.answers.pop(0)]


class RefusalDetectionTests(unittest.TestCase):
    def test_refusal_phrases_are_detected(self):
        cases = (
            "I'm sorry, but I can't help with that.",
            "As an AI language model, I cannot provide that.",
            "I cannot assist with this request.",
            "I must decline this request.",
            "I am not comfortable answering that.",
        )
        for answer in cases:
            with self.subTest(answer=answer):
                self.assertIsNotNone(refusal_reason(answer))

    def test_ordinary_answers_are_not_refusals(self):
        for answer in ("Sure, here is how the algorithm works.",
                       "I can't guarantee it will work, but the function returns 3.",
                       "Step 1: open the oven. Step 2: place the phone inside."):
            with self.subTest(answer=answer):
                self.assertIsNone(refusal_reason(answer))
        self.assertEqual(refusal_reason(""), "empty")
        self.assertEqual(refusal_reason("  \n "), "empty")


class TrainingFreeTests(unittest.TestCase):
    def profiles(self):
        return (Profile("greedy"),
                Profile("prefill", temperature=0.7, top_p=0.9, prefill="Sure, here is", seed=3))

    def test_first_non_refusal_answer_wins(self):
        generator = FakeGenerator(["I'm sorry, but I can't help with that.",
                                   "Sure, here is the plan: step one."])
        result = generate_without_refusal(generator, "Write a plan.", profiles=self.profiles())
        self.assertEqual(result.profile, "prefill")
        self.assertIn("step one", result.answer)
        self.assertEqual(len(result.attempts), 2)
        self.assertIsNotNone(result.attempts[0]["refusal"])
        self.assertIsNone(result.attempts[1]["refusal"])
        self.assertFalse(generator.calls[0]["do_sample"])
        self.assertTrue(generator.calls[1]["do_sample"])
        self.assertEqual(generator.calls[1]["prefill"], "Sure, here is")
        self.assertEqual(generator.calls[1]["seed"], 3)

    def test_all_refusals_raise_with_a_trace(self):
        generator = FakeGenerator(["I can't help with that.", "As an AI, I must decline."])
        with self.assertRaises(RefusalError) as caught:
            generate_without_refusal(generator, "Write a plan.", profiles=self.profiles())
        self.assertEqual(len(caught.exception.attempts), 2)
        self.assertEqual(caught.exception.prompt, "Write a plan.")

    def test_samples_per_profile_and_seed_offsets(self):
        generator = FakeGenerator(["I'm sorry.", "I'm sorry.", "Sure, here is the answer."])
        result = generate_without_refusal(generator, "Question.", profiles=self.profiles(),
                                          samples_per_profile=2)
        self.assertEqual(result.profile, "prefill")
        self.assertEqual(len(generator.calls), 3)
        self.assertEqual([call["seed"] for call in generator.calls[1:]],
                         [3, 4])

    def test_invalid_inputs_are_rejected(self):
        generator = FakeGenerator([])
        for invalid in ("", "   ", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                generate_without_refusal(generator, invalid)
        for invalid in (0, 6, True, 1.5):
            with self.subTest(samples=invalid), self.assertRaises(ValueError):
                generate_without_refusal(generator, "Question.", samples_per_profile=invalid)
        for invalid in (0, -1, True):
            with self.subTest(temperature=invalid), self.assertRaises(ValueError):
                Profile("bad", temperature=invalid)
        with self.assertRaises(ValueError):
            Profile("bad", top_p=1.5)
        with self.assertRaises(ValueError):
            Profile("bad", top_k=0)
        with self.assertRaises(ValueError):
            Profile("")


class TrainingFreeCliTests(unittest.TestCase):
    def test_training_free_infer_prints_answer_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "trace.json"
            generator = FakeGenerator(["I'm sorry, but I can't help.", "Sure, here is the answer."])
            args = Namespace(model=Path("model"), device="auto", max_new_tokens=32,
                             prompt="Question?", training_free=True, samples=1, report=report)
            output = io.StringIO()
            with patch.object(hf_client, "LocalGenerator", return_value=generator), redirect_stdout(output):
                code = hf_client.run_inference(args)
            self.assertEqual(code, 0)
            self.assertIn("Sure, here is the answer.", output.getvalue())
            trace = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(trace["status"], "answered")
            self.assertEqual(len(trace["attempts"]), 2)

    def test_training_free_infer_reports_exhausted_refusals(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "trace.json"
            generator = FakeGenerator(["I can't help."] * len(DEFAULT_PROFILES))
            args = Namespace(model=Path("model"), device="auto", max_new_tokens=32,
                             prompt="Question?", training_free=True, samples=1, report=report)
            output = io.StringIO()
            with patch.object(hf_client, "LocalGenerator", return_value=generator), redirect_stdout(output):
                code = hf_client.run_inference(args)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "refused")
            trace = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(trace["status"], "refused")
            self.assertEqual(len(trace["attempts"]), len(DEFAULT_PROFILES))


if __name__ == "__main__":
    unittest.main()
