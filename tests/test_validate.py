"""Tests for parser/validate.py. Run with: python3 -m unittest discover tests"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "parser"))
import validate  # noqa: E402


def course(code, title="Some Course", units=3.0):
    return {"code": code, "title": title, "units": units}


def single(code, title="Some Course"):
    return {"articulated": True, "logic": "single", "courses": [course(code, title)]}


def row(dest, ccsf):
    return {"ucb_requirement": dest, "ccsf_equivalent": ccsf,
            "same_institution_required": False, "sequence_only": False}


def agreement(source="CCSF_to_UCLA_Test_BS.pdf", inst="University of California, Los Angeles",
              groups=None):
    if groups is None:
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [row(single("MATH 31A"), single("MATH 110A")),
                                         row(single("MATH 31B"), single("MATH 110B"))]}]
    return {"metadata": {"source_file": source, "major": "Test", "degree_type": "B.S.",
                         "academic_year": "2025-2026", "to_institution": inst},
            "requirement_sections": [{"section_name": "REQUIRED", "groups": groups}]}


def codes_for(results, idx=0):
    return {i["code"] for i in results[idx]["issues"]}


class ValidatorTests(unittest.TestCase):
    def run_one(self, ag, verified=()):
        return validate.validate([ag], verified=set(verified))

    def test_clean_agreement_passes(self):
        r = self.run_one(agreement())
        self.assertEqual(r[0]["status"], "auto-parsed")
        self.assertEqual(r[0]["errors"], 0)

    def test_verified_status(self):
        r = self.run_one(agreement(), verified={"CCSF_to_UCLA_Test_BS.pdf"})
        self.assertEqual(r[0]["status"], "verified")
        self.assertFalse(r[0]["regression"])

    def test_verified_with_errors_is_regression(self):
        ag = agreement(groups=[])
        r = self.run_one(ag, verified={"CCSF_to_UCLA_Test_BS.pdf"})
        self.assertEqual(r[0]["status"], "needs review")
        self.assertTrue(r[0]["regression"])

    def test_empty_agreement(self):
        self.assertIn("empty_agreement", codes_for(self.run_one(agreement(groups=[]))))

    def test_school_mismatch(self):
        ag = agreement(source="CCSF_to_SJSU_Test_BS.pdf")  # header still says UCLA
        self.assertIn("school_mismatch", codes_for(self.run_one(ag)))

    def test_missing_institution_is_warning_only(self):
        ag = agreement(inst=None)
        r = self.run_one(ag)
        self.assertIn("no_to_institution", codes_for(r))
        self.assertEqual(r[0]["status"], "auto-parsed")

    def test_wrong_school_codes(self):
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [row(single("MATH 226"), single("MATH 110A")),
                                         row(single("MATH 227"), single("MATH 110B"))]}]
        ag = agreement(source="CCSF_to_SJSU_Test_BS.pdf", inst=None, groups=groups)
        self.assertIn("wrong_school_codes", codes_for(self.run_one(ag)))

    def test_empty_group(self):
        groups = agreement()["requirement_sections"][0]["groups"] + [
            {"group_number": 2, "completion_rule": "Complete the following",
             "subgroups": [{"label": "A", "articulation_rows": []}]}]
        self.assertIn("empty_group", codes_for(self.run_one(agreement(groups=groups))))

    def test_pick_one_from_plain_rows_is_fine(self):
        # The matcher counts courses for "Complete 1 course from the following".
        groups = [{"group_number": 1, "completion_rule": "Complete 1 course from the following",
                   "subgroups": [],
                   "articulation_rows": [row(single("PSYCH 1"), single("PSYC 1")),
                                         row(single("PSYCH 2"), single("PSYC 2")),
                                         row(single("PSYCH 3"), single("PSYC 3"))]}]
        r = self.run_one(agreement(groups=groups))
        self.assertEqual(r[0]["status"], "auto-parsed")

    def test_count_rule_over_subgroups_is_ambiguous_warning(self):
        groups = [{"group_number": 1, "completion_rule": "Complete 1 course from the following",
                   "subgroups": [{"label": "A", "articulation_rows": [row(single("X 1"), single("A 1"))]},
                                 {"label": "B", "articulation_rows": [row(single("X 2"), single("B 1"))]}]}]
        r = self.run_one(agreement(groups=groups))
        self.assertIn("count_rule_ambiguous", codes_for(r))
        self.assertEqual(r[0]["status"], "auto-parsed")

    def test_row_with_both_sides_empty_is_error(self):
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [row({"articulated": False}, {"articulated": False})]}]
        r = self.run_one(agreement(groups=groups))
        self.assertIn("row_empty", codes_for(r))
        self.assertEqual(r[0]["status"], "needs review")

    def test_word_requirement_is_warning_only(self):
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [row({"articulated": False}, single("ENGL C1000"))]}]
        r = self.run_one(agreement(groups=groups))
        self.assertIn("dest_unparsed", codes_for(r))
        self.assertEqual(r[0]["status"], "auto-parsed")

    def test_long_cross_department_and_list_is_error(self):
        ccsf = {"articulated": True, "logic": "AND",
                "courses": [course(c) for c in ["ECON 5", "MATH 70", "PHIL 12A", "PSYC 5", "STAT C1000"]]}
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [row(single("STATS 10"), ccsf)]}]
        self.assertIn("suspicious_and_list", codes_for(self.run_one(agreement(groups=groups))))

    def test_short_sequence_is_fine(self):
        ccsf = {"articulated": True, "logic": "AND",
                "courses": [course("PHYC 4A"), course("PHYC 4AL")]}
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [row(single("PHYSICS 1A"), ccsf)]}]
        self.assertNotIn("suspicious_and_list", codes_for(self.run_one(agreement(groups=groups))))

    def test_garbled_and_truncated_titles(self):
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": [
                       row(single("MATH 33B", "Di!erential Equations"), single("MATH 125")),
                       row(single("MATH 31A"), single("PHYC 4BL", "Electromagnetism Laboratory for"))]}]
        found = codes_for(self.run_one(agreement(groups=groups)))
        self.assertIn("garbled_text", found)
        self.assertIn("truncated_title", found)

    def test_duplicate_across_schools(self):
        base = agreement()
        rows_ = [row(single(f"MATH {n}"), single(f"MATH {n}0")) for n in range(1, 7)]
        base["requirement_sections"][0]["groups"][0]["articulation_rows"] = rows_
        a = copy.deepcopy(base)
        b = copy.deepcopy(base)
        b["metadata"].update(source_file="CCSF_to_SFSU_Test_BS.pdf",
                             to_institution="San Francisco State University")
        results = validate.validate([a, b], verified=set())
        self.assertIn("duplicate_other_school", codes_for(results, 0))
        self.assertIn("duplicate_other_school", codes_for(results, 1))
        self.assertTrue(all(r["status"] == "needs review" for r in results))

    def test_duplicate_blames_only_the_mislabeled_copy(self):
        rows_ = [row(single(c), single(f"MATH {i}")) for i, c in
                 enumerate(["MATH 226", "MATH 227", "MATH 228", "MATH 1", "MATH 2", "MATH 3"])]
        groups = [{"group_number": 1, "completion_rule": "Complete the following", "subgroups": [],
                   "articulation_rows": rows_}]
        sfsu = agreement(source="CCSF_to_SFSU_Math_BS.pdf", inst="San Francisco State University",
                         groups=copy.deepcopy(groups))
        sjsu = agreement(source="CCSF_to_SJSU_Math_BS.pdf", inst=None, groups=copy.deepcopy(groups))
        results = validate.validate([sfsu, sjsu], verified=set())
        self.assertEqual(results[0]["status"], "auto-parsed")
        self.assertEqual(results[1]["status"], "needs review")
        self.assertIn("wrong_school_codes", codes_for(results, 1))


class RealDataTests(unittest.TestCase):
    """Guards on the committed data: hand-verified agreements must keep passing."""

    def test_verified_agreements_still_pass(self):
        import json
        data = json.loads(validate.DEFAULT_DATA.read_text())
        results = validate.validate(data)
        regressions = [r["source_file"] for r in results if r["regression"]]
        self.assertEqual(regressions, [], f"Verified agreements now have errors: {regressions}")


if __name__ == "__main__":
    unittest.main()
