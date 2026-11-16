"""Tests for the USC agreement (usc.py, parser/parse_usc.py, USC endpoints)."""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import usc  # noqa: E402
from matcher import match_agreement  # noqa: E402

USC = json.loads((REPO / "USC_CCSF_agreement.json").read_text())
PDF = REPO / "data" / "source_pdfs" / "USC-Articulation_Agreement.pdf"


class UscDataTests(unittest.TestCase):
    def test_ge_categories(self):
        cats = USC["ge_requirements"]["core_literacy"]["categories"]
        self.assertEqual(sum(c["courses_required"] for c in cats.values()), 8)
        self.assertIn("BIO 32 with BIO 32L", cats["D_life_sciences"]["ccsf_courses"])
        self.assertIn("POLS C1000", cats["C_social_analysis"]["ccsf_courses"])

    def test_language_levels_follow_pdf_columns(self):
        levels = USC["ge_requirements"]["foreign_language"]["levels"]
        self.assertIn("JAPA 3 / JAPA 3A with JAPA 3B", levels["level_3"])
        self.assertIn("FREN 4", levels["level_4"])
        self.assertIn("CHIN 4 / CHIN 4A with CHIN 4B", levels["level_4"])

    def test_part3_and_part4_dont_overlap(self):
        for prefix, nums in USC["non_transferable"].items():
            for n in nums:
                self.assertNotIn(n, USC["transferable"].get(prefix, {}), f"{prefix} {n}")

    @unittest.skipUnless(PDF.exists(), "source PDF not in repo")
    def test_parser_reproduces_committed_data(self):
        try:
            sys.path.insert(0, str(REPO / "parser"))
            import parse_usc
        except ImportError as e:
            self.skipTest(f"pdfplumber missing: {e}")
        fresh = parse_usc.parse(str(PDF))
        self.assertEqual(fresh["_parse_warnings"], [])
        for key in ("ge_requirements", "course_equivalences", "transferable", "non_transferable"):
            self.assertEqual(fresh[key], USC[key], key)


class UscLogicTests(unittest.TestCase):
    def test_agreement_scores_ge(self):
        ag = usc.build_usc_agreement(USC)
        r = match_agreement(ag, ["ENGL C1001", "CHEM 101A", "MATH 110A"])
        groups = {g["completion_rule"] + str(g["group_number"]): g["status"]
                  for s in r["sections"] for g in s["groups"]}
        self.assertEqual(r["sections"][2]["status"], "complete")  # writing
        self.assertIn("complete", groups.values())
        self.assertNotEqual(r["overall"]["status"], "complete")

    def test_two_course_categories(self):
        ag = usc.build_usc_agreement(USC)
        r = match_agreement(ag, ["HIST 4A"])
        b = r["sections"][0]["groups"][1]
        self.assertEqual(b["completion_rule"], "Complete 2 courses from the following")
        self.assertEqual((b["status"], b["progress"]), ("in_progress", 0.5))

    def test_transfer_status(self):
        self.assertEqual(usc.transfer_status(USC, "MATH 110A")["status"], "transfers")
        self.assertEqual(usc.transfer_status(USC, "RE 181")["status"], "does_not_transfer")
        self.assertEqual(usc.transfer_status(USC, "R E 181")["status"], "does_not_transfer")
        self.assertEqual(usc.transfer_status(USC, "CHIN 1A")["status"], "transfers_with_conditions")
        self.assertEqual(usc.transfer_status(USC, "PHYS 4A")["status"], "not_listed")

    def test_language_level(self):
        self.assertEqual(usc.language_level(USC, ["JAPA 3A", "JAPA 3B"])["level"], 3)
        self.assertEqual(usc.language_level(USC, ["JAPA 3A"])["level"], 0)

    def test_equivalences(self):
        eq = {tuple(e["ccsf_courses"]): e for e in usc.equivalences(USC, ["CHEM 101A", "BIO 100A"], [])}
        self.assertEqual(eq[("CHEM 101A",)]["status"], "complete")
        self.assertEqual(eq[("BIO 100A", "BIO 101B")]["status"], "in_progress")


try:
    from fastapi.testclient import TestClient
    import api
    CLIENT = TestClient(api.app)
except Exception:
    CLIENT = None


@unittest.skipIf(CLIENT is None, "fastapi + httpx needed for API tests")
class UscApiTests(unittest.TestCase):
    def test_find_returns_school_wide(self):
        r = CLIENT.get("/agreements/find", params={"school": "USC (University of Southern California)",
                                                    "major": "Bioengineering"}).json()
        self.assertEqual(r["count"], 0)
        self.assertEqual(r["school_wide"]["school"], "USC")
        self.assertIn("no major-specific", r["message"])

    def test_match_usc(self):
        r = CLIENT.post("/match/usc", json={"completed_courses": ["CHEM 101A", "RE 181"]})
        self.assertEqual(r.status_code, 200)
        r = r.json()
        self.assertIn("ge", r)
        checks = {c["code"]: c["status"] for c in r["transfer_check"]}
        self.assertEqual(checks["RE 181"], "does_not_transfer")

    def test_old_usc_ge_endpoint_still_works(self):
        self.assertEqual(CLIENT.post("/match/usc/ge", json={"completed_courses": ["ART 101"]}).status_code, 200)

    def test_spaces_in_codes(self):
        codes = [c["code"] for c in CLIENT.get("/courses", params={"q": "RE"}).json()["courses"]]
        self.assertIn("R E 181", codes)
        known = CLIENT.post("/courses/check", json={"codes": ["RE 181"]}).json()["known"]
        self.assertEqual(known[0]["code"], "R E 181")

    def test_schools_counts_usc_once(self):
        schools = {s["name"]: s["agreement_count"] for s in CLIENT.get("/schools").json()["schools"]}
        self.assertEqual(schools["USC"], 1)


if __name__ == "__main__":
    unittest.main()
