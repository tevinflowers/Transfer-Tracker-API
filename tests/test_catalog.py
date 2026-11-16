"""Tests for the CCSF catalog: parser/parse_catalog.py, data/ccsf_catalog.json, and the API."""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "parser"))
import parse_catalog  # noqa: E402

SAMPLE = """
Accounting (ACCT)
ACCT 1 -Financial Accounting (5.0)
Credit (Degree Applicable)
Introduction to accounting information system.
UC Transferable
ADMJ 71 -Student Campus Patrol Work Experience (1.0-3.0)
Credit (Degree Applicable)
CDEV 64 -Introduction to Stress Reduction and Coping in Early Childhood and Elementary School
(3.0)
Credit (Degree Applicable)
ENGL C1003 -Critical Thinking and Writing through Literature (4.0)
Credit (Degree Applicable)
Catalog Notes: Formerly ENGL 1B
UC Transferable
SPAN 2 -Elementary Spanish II (5.0)
Credit (Degree Applicable)
Catalog Notes: Formerly SPAN 2A + 2B
R E 184 -Real Estate Practice (3.0)
Credit (Degree Applicable)
CCSF Catalog - 2026/27 Page 600
PE A 60 -Women's Intercollegiate Soccer (3.0)
Noncredit
"""


SAMPLE_2025 = """
Credit, Degree Applicable Courses:
JAPA 1. Elementary Japanese (5)
Lec-87.5 P/NP available
Introductory course in grammar, reading, writing and Japanese cul-
ture. UC/CSU
JAPA 1A. Elementary Japanese Part I (3)
Lec-52.5 P/NP available
Half of the introductory course.
ADMJ 71. Student Campus Patrol Work Experience (1-3)
CSU
LERN 10. Study Skills (.5)
"""


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.courses, cls.depts, _ = parse_catalog.parse_lines(SAMPLE.splitlines())

    def test_basic_entry(self):
        c = self.courses["ACCT 1"]
        self.assertEqual((c["title"], c["units"], c["uc_transferable"]), ("Financial Accounting", 5.0, True))
        self.assertEqual(self.depts["ACCT"], "Accounting")

    def test_unit_range(self):
        c = self.courses["ADMJ 71"]
        self.assertEqual((c["units"], c["units_max"]), (1.0, 3.0))

    def test_wrapped_title(self):
        self.assertEqual(self.courses["CDEV 64"]["units"], 3.0)

    def test_prefixes_with_spaces(self):
        self.assertIn("R E 184", self.courses)
        self.assertEqual(self.courses["PE A 60"]["credit_type"], "Noncredit")

    def test_one_to_one_renames_only(self):
        self.assertEqual(self.courses["ENGL C1003"]["formerly"], ["ENGL 1B"])
        self.assertEqual(self.courses["SPAN 2"]["formerly"], [])  # "SPAN 2A + 2B" isn't a rename

    def test_two_column_2025_format(self):
        courses, _, _ = parse_catalog.parse_lines(SAMPLE_2025.splitlines())
        self.assertEqual((courses["JAPA 1"]["title"], courses["JAPA 1"]["units"]), ("Elementary Japanese", 5.0))
        self.assertTrue(courses["JAPA 1"]["uc_transferable"])
        self.assertFalse(courses["JAPA 1A"]["uc_transferable"])
        self.assertEqual((courses["ADMJ 71"]["units"], courses["ADMJ 71"]["units_max"]), (1.0, 3.0))
        self.assertEqual(courses["LERN 10"]["units"], 0.5)

    def test_merge_years(self):
        a = parse_catalog.merge(None, "2025-26", {"X 1": {"code": "X 1", "title": "Old", "formerly": []}}, {}, {})
        b = parse_catalog.merge(a, "2026-27", {"X 1": {"code": "X 1", "title": "New", "formerly": []}}, {}, {})
        self.assertEqual(b["courses"]["X 1"]["title"], "New")
        self.assertEqual(b["courses"]["X 1"]["catalog_years"], ["2025-26", "2026-27"])


class CatalogDataTests(unittest.TestCase):
    def test_committed_catalog(self):
        data = json.loads((REPO / "data" / "ccsf_catalog.json").read_text())
        self.assertEqual(data["catalog_years"], ["2025-26", "2026-27"])
        self.assertEqual(data["courses"]["ENGL 1B"]["catalog_years"], ["2025-26"])
        self.assertEqual(data["courses"]["R E 184"]["catalog_years"], ["2025-26", "2026-27"])
        self.assertGreater(len(data["courses"]), 1800)
        c = data["courses"]
        self.assertEqual(c["MATH 110A"]["title"], "Calculus I")
        self.assertEqual(c["R E 184"]["title"], "Real Estate Practice")
        self.assertIn("ENGL 1A", c["ENGL C1000"]["formerly"])


try:
    from fastapi.testclient import TestClient
    import api
    CLIENT = TestClient(api.app)
except Exception:
    CLIENT = None


@unittest.skipIf(CLIENT is None, "fastapi + httpx needed for API tests")
class CatalogApiTests(unittest.TestCase):
    def search(self, q):
        return [c["code"] for c in CLIENT.get("/courses", params={"q": q, "limit": 50}).json()["courses"]]

    def test_every_catalog_course_is_searchable(self):
        self.assertIn("R E 184", self.search("RE"))
        self.assertIn("R E 184", self.search("real estate"))
        self.assertIn("PSYC C1000", self.search("intro psych"))

    def test_natural_order_and_current_first(self):
        codes = self.search("MATH 1")
        self.assertLess(codes.index("MATH 100A"), codes.index("MATH 110A"))
        r = CLIENT.get("/courses", params={"q": "ENGL 1", "limit": 50}).json()["courses"]
        code_matches = [c for c in r if c["code"].replace(" ", "").startswith("ENGL1")]
        flags = [c["in_current_catalog"] is False for c in code_matches]
        self.assertEqual(flags, sorted(flags))  # current codes first, then old ones (ENGL 1A, 1B, 1C)

    def test_dropped_course_points_to_new_code(self):
        known = CLIENT.post("/courses/check", json={"codes": ["ENGL 1B", "ART 101"]}).json()["known"]
        self.assertEqual({k["code"]: k["renamed_to"] for k in known},
                         {"ENGL 1B": "ENGL C1003", "ART 101": "ARTH C1100"})
        self.assertTrue(all(k["in_current_catalog"] is False for k in known))

    def test_renamed_code_satisfies_old_agreement_code(self):
        # The Berkeley Bioengineering R&C row lists ENGL 1B (now ENGL C1003).
        r = CLIENT.post("/match/46", json={"completed_courses": ["ENGL C1003"]}).json()
        rc = [row for s in r["sections"] for g in s["groups"] for sg in g["subgroups"]
              for row in sg["rows"] if "ENGL 1B" in (row["ccsf_equivalent"] or "")]
        self.assertEqual(rc[0]["status"], "complete")
        self.assertEqual(r["student"]["completed_courses"], ["ENGL C1003"])  # not the expanded list

    def test_old_code_satisfies_new_code(self):
        # USC writing lists ENGL C1001; ENGL 1C is its old code.
        r = CLIENT.post("/match/usc", json={"completed_courses": ["ENGL 1C"]}).json()
        writing = r["ge"]["sections"][2]
        self.assertEqual(writing["status"], "complete")


if __name__ == "__main__":
    unittest.main()
