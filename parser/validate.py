"""
Agreement validator: checks parsed ASSIST agreements before the app uses them.

Run it after every parse:

    python3 parser/validate.py                       # checks all_agreements_v3.json
    python3 parser/validate.py some_other_file.json  # checks another file
    python3 parser/validate.py --details             # list every issue, not just counts
    python3 parser/validate.py --json report.json    # also save a machine-readable report
    python3 parser/validate.py --strict              # exit with code 1 if anything needs review

Each agreement gets a status:
    verified      hand-checked (listed in parser/verified.json) and no errors
    auto-parsed   no errors (warnings are OK); not hand-checked
    needs review  at least one error: don't trust its readiness % until fixed

Issue levels:
    error    the data is wrong or the matcher will compute a wrong result
    warning  probably wrong or ugly, but matching still works
    info     cosmetic; counted in the summary only
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from matcher import parse_completion_rule  # noqa: E402  (same rule logic the API uses)

DEFAULT_DATA = REPO / "all_agreements_v3.json"
VERIFIED_FILE = HERE / "verified.json"

# ── School identification ─────────────────────────────────────────────────────

# Filename token after "CCSF_to_" → school name
FILENAME_SCHOOLS = {
    "UCBERKELEY": "UC Berkeley", "UCB": "UC Berkeley",
    "UCLA": "UCLA",
    "UCD": "UC Davis", "UCDAVIS": "UC Davis",
    "SFSU": "SFSU",
    "SJSU": "SJSU",
}

# Words in metadata.to_institution → school name
INSTITUTION_KEYWORDS = [
    ("berkeley", "UC Berkeley"),
    ("los angeles", "UCLA"),
    ("davis", "UC Davis"),
    ("san francisco state", "SFSU"),
    ("san jose state", "SJSU"),
]

# Calculus course codes are distinctive per campus. If an agreement's destination
# side uses another school's codes and none of its own, the file is probably
# mislabeled (this is how the SJSU-files-are-really-SFSU problem shows up).
# Extend this table when new schools are added.
SCHOOL_FINGERPRINTS = {
    "UC Berkeley": {"MATH 1A", "MATH 1B", "MATH 53", "MATH 54"},
    "UCLA":        {"MATH 31A", "MATH 31B", "MATH 32A", "MATH 32B", "MATH 33A"},
    "UC Davis":    {"MATH 21A", "MATH 21B", "MATH 21C", "MATH 21D"},
    "SFSU":        {"MATH 226", "MATH 227", "MATH 228"},
    "SJSU":        {"MATH 30", "MATH 31", "MATH 32"},
}

GARBLED_RE   = re.compile(r'\w[!"]\w')   # ligature damage, e.g. Di!erential, So"ware
TRUNCATED_RE = re.compile(r'(\b(for|and|of|the|to|in|with|&)|[:,(\-])$', re.IGNORECASE)
RULE_LETTERS_RE = re.compile(r'\b([A-F])\b')


def school_from_filename(name):
    m = re.match(r'CCSF_to_([A-Za-z]+)_', name or "")
    return FILENAME_SCHOOLS.get(m.group(1).upper()) if m else None


def school_from_institution(inst):
    low = (inst or "").lower()
    for key, school in INSTITUTION_KEYWORDS:
        if key in low:
            return school
    return inst or None


# ── Walking the agreement ─────────────────────────────────────────────────────

def side_options(side):
    """Return the course lists on one side of a row: one list, or one per OR option."""
    if not side or not side.get("articulated"):
        return []
    if side.get("options"):
        return [o.get("courses", []) for o in side["options"]]
    return [side.get("courses", [])]


def side_codes(side):
    return [c.get("code", "") for opt in side_options(side) for c in opt]


def iter_rows(ag):
    """Yield (section, group, subgroup_or_None, row) for every articulation row."""
    for s in ag.get("requirement_sections", []):
        for g in s.get("groups", []):
            for r in g.get("articulation_rows", []) or []:
                yield s, g, None, r
            for sg in g.get("subgroups", []) or []:
                for r in sg.get("articulation_rows", []) or []:
                    yield s, g, sg, r


def row_signature(row):
    return (tuple(sorted(side_codes(row.get("ucb_requirement", {})))),
            tuple(sorted(side_codes(row.get("ccsf_equivalent", {})))))


# ── Checks ────────────────────────────────────────────────────────────────────

class Issues:
    def __init__(self):
        self.items = []

    def add(self, level, code, message, where=""):
        self.items.append({"level": level, "code": code, "message": message, "where": where})

    def count(self, level):
        return sum(1 for i in self.items if i["level"] == level)


def where_of(section, group, subgroup):
    parts = [section.get("section_name", "?"), f"group {group.get('group_number', '?')}"]
    if subgroup is not None:
        parts.append(f"subgroup {subgroup.get('label', '?')}")
    return " / ".join(parts)


def check_metadata(ag, iss):
    m = ag.get("metadata", {})
    fname = m.get("source_file", "")
    from_file = school_from_filename(fname)
    from_inst = school_from_institution(m.get("to_institution"))

    if not from_file and not from_inst:
        iss.add("error", "school_unknown", "Can't tell which school this is (no to_institution, unrecognized filename).")
    elif from_file and from_inst and from_file != from_inst:
        iss.add("error", "school_mismatch",
                f"Filename says {from_file} but the PDF header says {from_inst}.")
    elif not m.get("to_institution"):
        iss.add("warning", "no_to_institution",
                "to_institution is empty (school taken from filename). Re-parse with the fixed parser.")

    for field in ("major", "degree_type", "academic_year"):
        if not m.get(field):
            iss.add("warning", f"no_{field}", f"metadata.{field} is empty.")
    return from_inst or from_file


def check_fingerprint(ag, school, iss):
    dest = {c for *_, r in iter_rows(ag) for c in side_codes(r.get("ucb_requirement", {}))}
    own = SCHOOL_FINGERPRINTS.get(school, set())
    if dest & own:
        return
    for other, codes in SCHOOL_FINGERPRINTS.items():
        if other != school and len(dest & codes) >= 2:
            iss.add("error", "wrong_school_codes",
                    f"Labeled {school} but uses {other} course codes "
                    f"({', '.join(sorted(dest & codes))}). Probably the wrong PDF or a mislabeled file.")
            return


def check_structure(ag, iss):
    rows = list(iter_rows(ag))
    if not rows:
        iss.add("error", "empty_agreement", "Agreement has no articulation rows at all.")
        return

    for s in ag.get("requirement_sections", []):
        for g in s.get("groups", []):
            w = where_of(s, g, None)
            subgroups = g.get("subgroups", []) or []
            direct = g.get("articulation_rows", []) or []
            has_rows = direct or any(sg.get("articulation_rows") for sg in subgroups)
            if not has_rows:
                iss.add("error", "empty_group", "Group has no rows (nothing to match against).", w)
                continue

            rule = g.get("completion_rule") or ""
            if not rule.strip():
                iss.add("warning", "no_rule", "Group has no completion rule; matcher assumes ALL required.", w)
                continue
            parsed = parse_completion_rule(rule)

            # "Complete 1 course from the following" with plain rows (no subgroups):
            # matcher.match_group treats direct rows as all-required, so this would be wrong.
            if not subgroups and len(direct) > 1 and parsed["subgroup_logic"] == "OR":
                need = parsed["min_count"] or 1
                if need < len(direct):
                    iss.add("error", "pick_n_matched_as_all",
                            f'Rule "{rule}" asks for {need} of {len(direct)} rows, but these rows '
                            f"aren't in subgroups, so the matcher requires all of them.", w)

            # Rule names subgroup letters that don't exist (or vice versa)
            letters = set(RULE_LETTERS_RE.findall(rule))
            labels = {sg.get("label") for sg in subgroups}
            if letters and subgroups and letters != labels:
                iss.add("warning", "rule_letters_mismatch",
                        f'Rule "{rule}" mentions {", ".join(sorted(letters))} but subgroups are '
                        f'{", ".join(sorted(l for l in labels if l))}.', w)


def check_rows(ag, iss):
    for s, g, sg, r in iter_rows(ag):
        w = where_of(s, g, sg)
        dest, ccsf = r.get("ucb_requirement", {}), r.get("ccsf_equivalent", {})
        ccsf_codes = side_codes(ccsf)

        if not dest.get("articulated") or not side_codes(dest):
            if ccsf_codes:
                # Often a requirement described in words (e.g. Berkeley "Reading &
                # Composition") rather than a course. Matching still works off the CCSF
                # side; only the requirement's name is missing in the app.
                preview = ", ".join(ccsf_codes[:4]) + ("…" if len(ccsf_codes) > 4 else "")
                iss.add("warning", "dest_unparsed",
                        f"University side has no course code; requirement name will be missing "
                        f"(CCSF side: {preview}).", w)
            else:
                iss.add("error", "row_empty",
                        "Both sides of this row are empty: a requirement was lost while parsing.", w)

        # Long AND lists across departments are almost always rows that bled together
        # or an OR-list misread as AND.
        if ccsf.get("articulated") and not ccsf.get("options"):
            courses = ccsf.get("courses", [])
            depts = {c.get("code", "").split()[0] for c in courses if c.get("code")}
            if len(depts) >= 3 and len(courses) >= 5:
                iss.add("error", "suspicious_and_list",
                        f"CCSF side requires ALL of {len(courses)} courses from {len(depts)} departments "
                        f"({', '.join(c['code'] for c in courses[:5])}{'…' if len(courses) > 5 else ''}). "
                        f"Almost certainly an OR list read as AND; the matcher will require every one.", w)
            elif len(depts) >= 3 or len(courses) >= 5:
                iss.add("warning", "suspicious_and_list",
                        f"CCSF side requires ALL of {len(courses)} courses from {len(depts)} departments "
                        f"({', '.join(c['code'] for c in courses[:5])}{'…' if len(courses) > 5 else ''}). "
                        f"Likely rows bled together or an OR list read as AND.", w)

        for side in (dest, ccsf):
            for opt in side_options(side):
                for c in opt:
                    title = c.get("title", "")
                    if GARBLED_RE.search(title):
                        iss.add("warning", "garbled_text", f'Garbled characters in title "{title}" ({c.get("code")}).', w)
                    elif TRUNCATED_RE.search(title.strip()):
                        iss.add("info", "truncated_title", f'Title looks cut off: "{title}" ({c.get("code")}).', w)


def check_duplicates(agreements, schools, issues_by_idx):
    """Flag agreements that are near-copies of an agreement for a different school/major."""
    sigs = [{row_signature(r) for *_, r in iter_rows(ag)} for ag in agreements]
    for i in range(len(agreements)):
        for j in range(i + 1, len(agreements)):
            a, b = sigs[i], sigs[j]
            if min(len(a), len(b)) < 5:
                continue
            overlap = len(a & b) / len(a | b)
            if overlap < 0.9:
                continue
            fi = agreements[i]["metadata"].get("source_file")
            fj = agreements[j]["metadata"].get("source_file")
            if schools[i] != schools[j]:
                wrong = {k for k in (i, j)
                         if any(x["code"] == "wrong_school_codes" for x in issues_by_idx[k].items)}
                for k, other, osch in ((i, fj, schools[j]), (j, fi, schools[i])):
                    if len(wrong) == 1 and k not in wrong:
                        # Course codes already show the *other* file is the mislabeled one.
                        issues_by_idx[k].add("warning", "duplicate_other_school",
                                             f"{overlap:.0%} identical to {other} ({osch}), which is the "
                                             f"mislabeled copy. This one looks right.")
                    else:
                        issues_by_idx[k].add("error", "duplicate_other_school",
                                             f"{overlap:.0%} identical to {other} ({osch}). One of them is "
                                             f"probably the wrong PDF.")
            else:
                for k, other in ((i, fj), (j, fi)):
                    issues_by_idx[k].add("warning", "duplicate_same_school",
                                         f"{overlap:.0%} identical to {other}. Check both majors are the right PDFs.")


# ── Running ───────────────────────────────────────────────────────────────────

def load_verified():
    if VERIFIED_FILE.exists():
        return set(json.loads(VERIFIED_FILE.read_text()).get("verified", []))
    return set()


def validate(agreements, verified=None):
    verified = verified if verified is not None else load_verified()
    issues = [Issues() for _ in agreements]
    schools = []
    for ag, iss in zip(agreements, issues):
        school = check_metadata(ag, iss)
        schools.append(school)
        if school:
            check_fingerprint(ag, school, iss)
        check_structure(ag, iss)
        check_rows(ag, iss)
    check_duplicates(agreements, schools, issues)

    results = []
    for idx, (ag, iss, school) in enumerate(zip(agreements, issues, schools)):
        m = ag.get("metadata", {})
        fname = m.get("source_file")
        errors = iss.count("error")
        if errors:
            status = "needs review"
        elif fname in verified:
            status = "verified"
        else:
            status = "auto-parsed"
        results.append({
            "id": idx,
            "source_file": fname,
            "school": school,
            "major": m.get("major"),
            "degree_type": m.get("degree_type"),
            "status": status,
            "regression": bool(errors and fname in verified),
            "errors": errors,
            "warnings": iss.count("warning"),
            "info": iss.count("info"),
            "issues": iss.items,
        })
    return results


def print_report(results, details=False, out=sys.stdout):
    def p(*a):
        print(*a, file=out)

    statuses = Counter(r["status"] for r in results)
    codes = Counter((i["level"], i["code"]) for r in results for i in r["issues"])
    p(f"Checked {len(results)} agreements")
    p(f"  verified:     {statuses['verified']}")
    p(f"  auto-parsed:  {statuses['auto-parsed']}")
    p(f"  needs review: {statuses['needs review']}")
    regressions = [r for r in results if r["regression"]]
    if regressions:
        p(f"\n!! {len(regressions)} hand-verified agreement(s) now have errors. The parser broke something:")
        for r in regressions:
            p(f"   - {r['source_file']}")

    p("\nIssues by type:")
    for level in ("error", "warning", "info"):
        for (lvl, code), n in sorted(codes.items(), key=lambda kv: -kv[1]):
            if lvl == level:
                p(f"  {level:<7} {code:<26} {n}")

    by_school = defaultdict(Counter)
    for r in results:
        by_school[r["school"] or "?"][r["status"]] += 1
    p("\nBy school:")
    for school in sorted(by_school):
        c = by_school[school]
        p(f"  {school:<12} verified {c['verified']:>2}   auto-parsed {c['auto-parsed']:>2}   needs review {c['needs review']:>2}")

    review = [r for r in results if r["status"] == "needs review"]
    if review:
        p("\nNeeds review (most errors first):")
        for r in sorted(review, key=lambda r: (-r["errors"], r["source_file"] or "")):
            p(f"  [{r['id']:>3}] {r['source_file']}  ({r['errors']} errors, {r['warnings']} warnings)")
            shown = [i for i in r["issues"] if i["level"] == "error"]
            if not details:
                shown = shown[:3]
            for i in shown:
                where = f"  [{i['where']}]" if i["where"] else ""
                p(f"        - {i['message']}{where}")
            hidden = r["errors"] - len(shown)
            if hidden > 0:
                p(f"        … {hidden} more (run with --details)")

    if details:
        p("\nWarnings for agreements that passed:")
        for r in results:
            if r["status"] != "needs review" and r["warnings"]:
                p(f"  [{r['id']:>3}] {r['source_file']}")
                for i in r["issues"]:
                    if i["level"] == "warning":
                        where = f"  [{i['where']}]" if i["where"] else ""
                        p(f"        - {i['message']}{where}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate parsed ASSIST agreements.")
    ap.add_argument("path", nargs="?", default=str(DEFAULT_DATA), help="agreements JSON file")
    ap.add_argument("--details", action="store_true", help="list every issue")
    ap.add_argument("--json", metavar="FILE", help="also write the full report as JSON")
    ap.add_argument("--strict", action="store_true", help="exit with code 1 if any agreement needs review")
    args = ap.parse_args(argv)

    with open(args.path) as f:
        agreements = json.load(f)
    results = validate(agreements)
    print_report(results, details=args.details)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nFull report written to {args.json}")

    if args.strict and any(r["status"] == "needs review" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
