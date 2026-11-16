"""API tests. Run with: python3 -m unittest discover tests (needs: pip3 install httpx)"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from fastapi.testclient import TestClient
    import api
    CLIENT = TestClient(api.app)
except Exception as e:  # fastapi/httpx not installed
    CLIENT = None
    SKIP_REASON = f"API test client unavailable: {e}"


@unittest.skipIf(CLIENT is None, "fastapi + httpx needed for API tests")
class ApiTests(unittest.TestCase):
    def test_health(self):
        r = CLIENT.get("/").json()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["agreements_loaded"], 112)

    def test_find_agreement(self):
        r = CLIENT.get("/agreements/find", params={"school": "berkeley", "major": "bioengineering"}).json()
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["agreements"][0]["school"], "UC Berkeley")
        self.assertEqual(r["agreements"][0]["data_status"], "verified")

    def test_find_agreement_no_data(self):
        r = CLIENT.get("/agreements/find", params={"school": "USC", "major": "Bioengineering"}).json()
        self.assertEqual(r["count"], 0)
        self.assertIn("no data yet", r["message"])

    def find(self, school, major):
        return CLIENT.get("/agreements/find", params={"school": school, "major": major}).json()

    def test_find_with_app_school_names(self):
        for name in ("UC Los Angeles (UCLA)", "University of California, Los Angeles", "ucla"):
            r = self.find(name, "Bioengineering")
            self.assertEqual((r["school"], r["count"]), ("UCLA", 1), name)
        r = self.find("San Jose State University", "Economics")
        self.assertEqual(r["school"], "SJSU")
        self.assertEqual(r["agreements"][0]["data_status"], "needs review")

    def test_csu_names_never_become_uc(self):
        self.assertNotEqual(self.find("Cal State LA", "Biology")["school"], "UCLA")
        self.assertNotEqual(self.find("California State University, Los Angeles", "Biology")["school"], "UCLA")

    def test_partial_major_is_a_suggestion_not_a_match(self):
        # "Engineering" must not silently become "Aerospace Engineering".
        r = self.find("UC Berkeley", "Engineering")
        self.assertEqual(r["count"], 0)
        self.assertIn("no data yet", r["message"])
        self.assertIn("Bioengineering", [x["major"] for x in r["suggestions"]])

    def test_major_name_normalization(self):
        self.assertEqual(self.find("UCLA", "Computer Science & Engineering")["count"], 1)
        self.assertEqual(self.find("UC Berkeley", "Film and Media")["count"], 1)

    def test_school_without_data(self):
        r = self.find("Sonoma State University", "Biology")
        self.assertEqual(r["count"], 0)
        self.assertFalse(r["school_has_data"])

    def test_find_route_not_shadowed_by_id_route(self):
        self.assertEqual(CLIENT.get("/agreements/find", params={"school": "ucla", "major": "x"}).status_code, 200)
        self.assertEqual(CLIENT.get("/agreements/46").status_code, 200)

    def test_summaries_have_data_status(self):
        for a in CLIENT.get("/agreements").json()["agreements"]:
            self.assertIn(a["data_status"], ("verified", "auto-parsed", "needs review"))

    def test_match_includes_status(self):
        r = CLIENT.post("/match/96", json={"completed_courses": ["ENGN 38"]}).json()
        self.assertEqual(r["agreement"]["id"], 96)
        self.assertEqual(r["agreement"]["data_status"], "verified")

    def test_course_search(self):
        codes = [c["code"] for c in CLIENT.get("/courses", params={"q": "phyc 4"}).json()["courses"]]
        self.assertIn("PHYC 4A", codes)
        self.assertTrue(CLIENT.get("/courses", params={"q": "calculus"}).json()["count"] >= 3)

    def test_course_check_suggests_fix(self):
        r = CLIENT.post("/courses/check", json={"codes": ["PHYS 4A", "phyc 4a", "ENGL 1A"]}).json()
        self.assertEqual([c["code"] for c in r["known"]], ["PHYC 4A"])
        sugg = {u["code"]: u["suggestions"] for u in r["unknown"]}
        self.assertEqual(sugg["PHYS 4A"][0], "PHYC 4A")
        self.assertEqual(sugg["ENGL 1A"], ["ENGL C1000"])

    def test_data_quality(self):
        r = CLIENT.get("/data-quality", params={"status": "verified"}).json()
        self.assertEqual(r["count"], 2)

    def test_existing_endpoints(self):
        self.assertEqual(CLIENT.get("/schools").status_code, 200)
        self.assertEqual(CLIENT.get("/majors", params={"school": "ucla"}).status_code, 200)
        self.assertEqual(CLIENT.post("/compare", json={"completed_courses": ["MATH 110A"]}).status_code, 200)
        self.assertEqual(CLIENT.post("/compare/school/sfsu", json={"completed_courses": []}).status_code, 200)
        self.assertEqual(CLIENT.post("/match/usc/ge", json={"completed_courses": ["ART 101"]}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
