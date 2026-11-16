"""Tests for parser/ligatures.py. Run with: python3 -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "parser"))
from ligatures import fix_in_data, fix_ligatures  # noqa: E402


class LigatureTests(unittest.TestCase):
    def test_known_repairs(self):
        self.assertEqual(fix_ligatures("Di!erential Equations"), "Differential Equations")
        self.assertEqual(fix_ligatures('Linear Algebra and Di"erential'), "Linear Algebra and Differential")
        self.assertEqual(fix_ligatures('So"ware Engineering'), "Software Engineering")
        self.assertEqual(fix_ligatures("So!ware"), "Software")
        self.assertEqual(fix_ligatures('A"er the Roman Empire'), "After the Roman Empire")
        self.assertEqual(fix_ligatures('Magic, Witchcra", and Religion'), "Magic, Witchcraft, and Religion")
        self.assertEqual(fix_ligatures("Complete 1 course in 3 di!erent areas."),
                         "Complete 1 course in 3 different areas.")

    def test_leaves_other_text_alone(self):
        for text in ("Calculus I", "Note! Read carefully", 'He said "hi"', "C++ Programming",
                     "Xy!zz", "", None):
            self.assertEqual(fix_ligatures(text), text)

    def test_fix_in_data(self):
        data = {"a": ["Di!erential", {"b": "ok"}], "n": 3}
        fixed, n = fix_in_data(data)
        self.assertEqual(fixed, {"a": ["Differential", {"b": "ok"}], "n": 3})
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
