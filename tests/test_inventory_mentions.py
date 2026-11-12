import unittest

from progprompt.inventory import missing_mentions


class InventoryMentionTests(unittest.TestCase):
    def test_longest_local_mention_preserves_other_separate_mentions(self):
        self.assertEqual(missing_mentions("Place the Mug on the Side Table near the table.",
                                          ["Mug", "SideTable"]), ["table"])
        self.assertEqual(missing_mentions("Move the sink basin and DeskLamp.", ["sink", "desk"]),
                         ["desklamp", "sinkbasin"])
        self.assertEqual(missing_mentions("Put it on the coffee-table.", ["Coffee Table"]), [])

    def test_only_explicit_words_are_compared(self):
        self.assertEqual(missing_mentions("Pass the cupboard, deskbound notes, and a MUG. Pick the mug.",
                                          ["desk", "cup"]), ["mug"])
        self.assertEqual(missing_mentions("Look for the desk. Lamp shades are nearby.",
                                          ["desklamp"]), ["desk"])
