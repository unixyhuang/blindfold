import unittest

from progprompt.benchmark import extract_program


class BenchmarkRunTests(unittest.TestCase):
    def test_one_program_per_response(self):
        program = "def plan():\n    find('book')"
        fenced = f"```python\n{program}\n```"
        self.assertEqual(extract_program(fenced + "\nA short explanation."),
                         (program + "\n", "single_block_with_prose"))
        for ambiguous in (fenced + "\n" + fenced, fenced + "\ndef other():\n    pass", fenced[:-3]):
            self.assertEqual(extract_program(ambiguous)[1], "invalid_envelope")
