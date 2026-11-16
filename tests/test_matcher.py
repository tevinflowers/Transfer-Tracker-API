"""Tests for matcher.py. Run with: python3 -m unittest discover tests"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from matcher import match_agreement, match_group, parse_completion_rule  # noqa: E402


def c(code, units=3.0):
    return {"code": code, "title": code, "units": units}


def row(dest, *ccsf, units=3.0):
    if ccsf:
        side = {"articulated": True, "logic": "single" if len(ccsf) == 1 else "AND",
                "courses": [c(x) for x in ccsf]}
    else:
        side = {"articulated": False}
    return {"ucb_requirement": {"articulated": True, "logic": "single", "courses": [c(dest, units)]},
            "ccsf_equivalent": side}


def group(rule, subgroups=None, rows=None):
    return {"group_number": 1, "completion_rule": rule,
            "subgroups": [{"label": l, "articulation_rows": r} for l, r in (subgroups or {}).items()],
            "articulation_rows": rows or []}


def status(g, done=(), prog=()):
    r = match_group(g, set(done), set(prog))
    return r["status"], r["progress"]


class RuleParsingTests(unittest.TestCase):
    def test_counts(self):
        p = parse_completion_rule("Complete 1 course from the following")
        self.assertEqual((p["count_unit"], p["count"]), ("course", 1))
        p = parse_completion_rule("Select 3 from the following")
        self.assertEqual((p["count_unit"], p["count"]), ("course", 3))
        p = parse_completion_rule("Complete 1 sequence from A, B, or C")
        self.assertEqual((p["count_unit"], p["count"]), ("sequence", 1))
        p = parse_completion_rule("Complete 1 series from A or B")
        self.assertEqual(p["count_unit"], "sequence")
        p = parse_completion_rule("Select 9.00 units from the following")
        self.assertEqual((p["count_unit"], p["min_units"]), ("units", 9.0))

    def test_areas(self):
        p = parse_completion_rule("Complete 1 course in 3 different areas.")
        self.assertEqual(p["count"], 3)
        p = parse_completion_rule("Complete 3 courses in 2 di!erent areas.")
        self.assertEqual(p["count"], 3)

    def test_per_subgroup(self):
        self.assertTrue(parse_completion_rule("Complete 1 course from A and B")["per_subgroup"])
        self.assertTrue(parse_completion_rule("Complete 1 course from A, B, and C")["per_subgroup"])
        self.assertFalse(parse_completion_rule("Complete 1 course from A")["per_subgroup"])
        self.assertFalse(parse_completion_rule("Complete A and B")["per_subgroup"])

    def test_no_count(self):
        for rule in ("Complete the following", "Complete A or B", "Complete A and B"):
            self.assertIsNone(parse_completion_rule(rule)["count_unit"], rule)


class GroupMatchingTests(unittest.TestCase):
    def test_one_course_from_a_list(self):
        g = group("Complete 1 course from A", {"A": [row("CS 31", "CS 110B"), row("CEE M20", "ENGN 38")]})
        self.assertEqual(status(g, done={"ENGN 38"}), ("complete", 1.0))
        self.assertEqual(status(g), ("not_started", 0.0))
        self.assertEqual(status(g, prog={"CS 110B"})[0], "in_progress")

    def test_one_course_across_subgroups(self):
        g = group("Complete 1 course from the following.",
                  {"A": [row("ENGIN 7", "ENGN 38"), row("CS 61A", "CS 111B")],
                   "B": [row("EECS 16A", "ENGN 16"), row("CS 61B", "CS 110C")]})
        self.assertEqual(status(g, done={"CS 110C"}), ("complete", 1.0))

    def test_two_courses_partial(self):
        g = group("Complete 2 courses from the following.",
                  rows=[row("X 1", "A 1"), row("X 2", "A 2"), row("X 3", "A 3")])
        self.assertEqual(status(g, done={"A 1"}), ("in_progress", 0.5))
        self.assertEqual(status(g, done={"A 1", "A 3"}), ("complete", 1.0))

    def test_from_a_and_b_needs_each(self):
        g = group("Complete 1 course from A and B",
                  {"A": [row("MATH 51", "MATH 110A"), row("MATH 16A", "MATH 100A")],
                   "B": [row("MATH 52", "MATH 110B"), row("MATH 16B", "MATH 100B")]})
        self.assertEqual(status(g, done={"MATH 110A"}), ("in_progress", 0.5))
        self.assertEqual(status(g, done={"MATH 110A", "MATH 100B"}), ("complete", 1.0))

    def test_sequence_counts_whole_subgroups(self):
        g = group("Complete 1 sequence from A or B",
                  {"A": [row("P 1", "PHYC 4A"), row("P 2", "PHYC 4B")],
                   "B": [row("P 7A", "PHYC 2A"), row("P 7B", "PHYC 2B")]})
        st, pr = status(g, done={"PHYC 4A"})
        self.assertEqual(st, "in_progress")
        self.assertEqual(pr, 0.5)
        self.assertEqual(status(g, done={"PHYC 4A", "PHYC 4B"}), ("complete", 1.0))

    def test_units(self):
        g = group("Select 9.00 units from the following",
                  {"A": [row("ACCT 100", "ACCT 1"), row("ACCT 101", "ACCT 2"), row("ART 222", "FASH 22")]})
        self.assertEqual(status(g, done={"ACCT 1"}), ("in_progress", 0.333))
        self.assertEqual(status(g, done={"ACCT 1", "ACCT 2", "FASH 22"}), ("complete", 1.0))

    def test_cannot_ask_for_more_than_ccsf_offers(self):
        # 3 units needed, but only one 1-unit row can be taken at CCSF.
        g = group("Complete 3.00 units from 1 of the following",
                  {"A": [row("ENGR 271", "ENGN 10B", units=1.0), row("ENGR 272", units=1.0)]})
        self.assertEqual(status(g, done={"ENGN 10B"}), ("complete", 1.0))
        g = group("Complete 2 courses from the following", rows=[row("X 1", "A 1"), row("X 2")])
        self.assertEqual(status(g, done={"A 1"}), ("complete", 1.0))

    def test_nothing_articulated_is_not_started(self):
        g = group("Complete 1 course from A", {"A": [row("X 1"), row("X 2")]})
        self.assertEqual(status(g, done={"A 1"}), ("not_started", 0.0))

    def test_unchanged_rules(self):
        g = group("Complete the following", rows=[row("X 1", "A 1"), row("X 2", "A 2")])
        self.assertEqual(status(g, done={"A 1"}), ("in_progress", 0.5))
        g = group("Complete A or B", {"A": [row("X 1", "A 1"), row("X 2", "A 2")], "B": [row("X 3", "B 1")]})
        self.assertEqual(status(g, done={"B 1"}), ("complete", 1.0))
        self.assertEqual(status(g, done={"A 1"})[0], "in_progress")
        g = group("Complete A and B", {"A": [row("X 1", "A 1")], "B": [row("X 3", "B 1")]})
        self.assertEqual(status(g, done={"A 1"}), ("in_progress", 0.5))


class RealAgreementTests(unittest.TestCase):
    """Hand-verified agreements: known student course sets must give known results."""

    @classmethod
    def setUpClass(cls):
        data = json.loads((REPO / "all_agreements_v3.json").read_text())
        cls.by_file = {a["metadata"]["source_file"]: a for a in data}

    def find_group(self, result, rule):
        return next(g for s in result["sections"] for g in s["groups"] if g["completion_rule"] == rule)

    def test_ucla_bioengineering_one_programming_course(self):
        ag = self.by_file["CCSF_to_UCLA_Bioengineering_BS.pdf"]
        r = match_agreement(ag, ["ENGN 38"])
        self.assertEqual(self.find_group(r, "Complete 1 course from A")["status"], "complete")

    def test_berkeley_bioengineering_one_course_from_list(self):
        ag = self.by_file["CCSF_to_UCBerkeley_Bioengineering_BS.pdf"]
        # ENGIN 7 needs ENGN 38 + ENGN 10B; COMPSCI 61B is satisfied by CS 110C alone.
        r = match_agreement(ag, ["ENGN 38"])
        self.assertEqual(self.find_group(r, "Complete 1 course from the following.")["status"], "in_progress")
        r = match_agreement(ag, ["CS 110C"])
        self.assertEqual(self.find_group(r, "Complete 1 course from the following.")["status"], "complete")

    def test_berkeley_bioengineering_everything_done(self):
        ag = self.by_file["CCSF_to_UCBerkeley_Bioengineering_BS.pdf"]
        every = sorted({k["code"] for s in ag["requirement_sections"] for g in s["groups"]
                        for rows in [g.get("articulation_rows", [])] +
                        [sg["articulation_rows"] for sg in g.get("subgroups") or []]
                        for r in rows
                        for o in (r["ccsf_equivalent"].get("options") or [r["ccsf_equivalent"]])
                        for k in o.get("courses", [])})
        self.assertEqual(match_agreement(ag, every)["overall"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
