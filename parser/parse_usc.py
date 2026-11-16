"""
USC ↔ CCSF articulation agreement parser.

USC isn't on ASSIST; it publishes one school-wide agreement per community college
("Undergraduate Transfer Credit Services → Articulation Agreements → Print Version").
That PDF has five parts:

    Part I    General requirements: GE Core Literacy A–F, Global Perspectives G–H,
              lower-division writing, foreign language levels
    Part II   Course-to-course equivalences (CCSF course → USC course)
    Part III  Every CCSF course that transfers for credit, by department
    Part IV   CCSF courses that do not transfer
    Part V    Rules (grades, unit limits, online courses, ...)

Usage:
    python3 parser/parse_usc.py USC-Articulation_Agreement.pdf > USC_CCSF_agreement.json

The output keeps the structure api.py and the app already use, and adds
"transferable" (Part III) and course codes for Part IV.
"""

import json
import re
import sys
from pathlib import Path

import pdfplumber

CATEGORY_KEYS = {
    "A": "A_arts", "B": "B_humanistic_inquiry", "C": "C_social_analysis",
    "D": "D_life_sciences", "E": "E_physical_sciences", "F": "F_quantitative_reasoning",
    "G": "G_citizenship_global_era", "H": "H_traditions_historical",
}

COURSE_NUM = r"[A-Z]{0,2}\d{1,4}[A-Z]{0,3}"
CODE_FLAGS = {
    "ONL": "Online or hybrid sections earn elective units only (no GE or language level).",
    "PTN": "Petition needed: no credit without review (submit syllabus).",
    "CDP": "Elective units; see the USC department for possible equivalence.",
    "DED": "Special review needed: non-traditional schedule or location.",
    "SYL": "Elective units; subject credit (e.g. GE) may be available by petition.",
    "WSY": "May satisfy the writing requirement by petition with writing samples.",
}


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def pdf_text(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def between(text, start, end):
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    return text[i:j]


# ── Part III: department name → prefix, and every transferable course ─────────

def expand(token):
    """'41-46' → 41..46; '200A-200C' → 200A, 200B, 200C; anything else as-is."""
    m = re.fullmatch(r"(\d+)([A-Z]?)-(\d+)([A-Z]?)", token)
    if not m:
        return [token]
    n1, l1, n2, l2 = m.groups()
    if l1 and l2 and n1 == n2:
        return [f"{n1}{chr(c)}" for c in range(ord(l1), ord(l2) + 1)]
    if not l1 and not l2 and int(n2) - int(n1) <= 30:
        return [str(n) for n in range(int(n1), int(n2) + 1)]
    return [f"{n1}{l1}", f"{n2}{l2}"]


def course_tokens(text):
    """Course numbers (with optional (ONL)-style codes) in a run of '; '-separated text."""
    out = []
    text = re.sub(r"(\d+[A-Z]?)-\s*$", r"\1", text)  # "47A-" broken across lines
    for m in re.finditer(rf"({COURSE_NUM}(?:-{COURSE_NUM})?)\s*(?:\(([A-Z]{{3}})\))?", text):
        for num in expand(m.group(1)):
            out.append((num, m.group(2)))
    return out


def is_note(line):
    """Explanatory text, not a course list. ("with" joins courses, so it doesn't count.)"""
    return bool(re.search(r"[a-z]", re.sub(r"\bwith\b", "", line))) or line.startswith(("NOTE", "EFFECTIVE"))


def parse_departments(section):
    """
    Returns ({dept name: prefix}, {prefix: {number: [flags]}}).
    A department appears as 'DEPT NAME <numbers>' then '(PREFIX ) <more numbers>'.
    """
    names, courses = {}, {}
    pending_name, pending_nums, prefix = None, [], None
    lines = [norm(l) for l in section.splitlines() if norm(l)]
    for line in lines:
        pm = re.match(r"^\(([A-Z][A-Z &]*?)\s*\)\s*(.*)$", line)
        if pm:
            prefix = norm(pm.group(1))
            if pending_name:
                names[pending_name] = prefix
            bucket = courses.setdefault(prefix, {})
            for num, flag in pending_nums:
                bucket.setdefault(num, set()).update([flag] if flag else [])
            rest = pm.group(2)
            if rest and not is_note(rest):
                for num, flag in course_tokens(rest):
                    bucket.setdefault(num, set()).update([flag] if flag else [])
            pending_name, pending_nums = None, []
            continue
        dm = re.match(rf"^([A-Z][A-Z :&/'.,()-]*?[A-Z)])\s+((?:{COURSE_NUM}).*)$", line)
        if dm and not is_note(line) and re.search(r"[A-Z]{2}", dm.group(1)):
            pending_name = norm(dm.group(1))
            pending_nums = course_tokens(dm.group(2))
            continue
        if prefix and not is_note(line) and re.fullmatch(rf"[\s;,]*(?:{COURSE_NUM}[\s;,()A-Z-]*)+", line):
            for num, flag in course_tokens(line):
                courses[prefix].setdefault(num, set()).update([flag] if flag else [])
    return names, {p: {n: sorted(f) for n, f in nums.items()} for p, nums in courses.items()}


# ── Part I: GE categories, writing, foreign language ──────────────────────────

def to_codes(dept, numbers, prefixes):
    """'BIO SCI: BIOLOGY', '32 with 32L; 100A' → ['BIO 32 with BIO 32L', 'BIO 100A']."""
    dept = norm(dept)
    ccn = dept.endswith("(CCN)")
    base = dept.replace("(CCN)", "").strip()
    prefix = prefixes.get(base) or prefixes.get(dept)
    if not prefix:
        return None
    out = []
    for part in [p.strip() for p in numbers.split(";") if p.strip()]:
        nums = [n.strip() for n in re.split(r"\s+with\s+", part)]
        out.append(" with ".join(f"{prefix} {n}" for n in nums))
    return out


def parse_course_table(block, prefixes, unknown):
    """Rows of 'DEPT NAME 1; 2; 3' (numbers can wrap onto the next line, before or after)."""
    codes = []
    lines = [norm(l) for l in block.splitlines() if norm(l)]
    carry = ""
    for i, line in enumerate(lines):
        if line.startswith(("Courses Course Code", "CATEGORY", "Courses")) or is_note(line):
            carry = ""
            continue
        m = re.match(rf"^(.*?[A-Z)])\s+((?:{COURSE_NUM})(?:\s*(?:;|with)\s*{COURSE_NUM})*\s*;?)$", line)
        if m and re.search(r"[A-Z]{2}", m.group(1)):
            nums = (carry + " " + m.group(2)).strip()
            carry = ""
            got = to_codes(m.group(1), nums, prefixes)
            if got is None:
                unknown.add(m.group(1))
            else:
                codes += got
        elif re.fullmatch(rf"(?:{COURSE_NUM}\s*(?:;|with)?\s*)+", line):
            # Numbers wrapped onto their own line: belong to the next or previous dept.
            if i + 1 < len(lines) and re.match(r"^[A-Z][A-Z :&/'.,()-]+$", lines[i + 1]):
                carry = line
            elif codes:
                prev_prefix = codes[-1].split()[0] if " with " not in codes[-1] else codes[-1].split()[0]
                for part in [p.strip() for p in line.split(";") if p.strip()]:
                    codes.append(" with ".join(f"{prev_prefix} {n.strip()}" for n in re.split(r"\s+with\s+", part)))
        elif re.match(r"^[A-Z][A-Z :&/'.,()-]+$", line) and carry:
            got = to_codes(line, carry, prefixes)
            carry = ""
            if got is None:
                unknown.add(line)
            else:
                codes += got
    return codes


def parse_part1(text, prefixes, unknown):
    cats = {}
    for m in re.finditer(r"CATEGORY ([A-H]): (.+?)(?: \((\d) courses? required\))?\n", text):
        letter, label, req = m.group(1), norm(m.group(2)), m.group(3)
        start = m.end()
        nxt = re.search(r"\nCATEGORY [A-H]:|\nGENERAL EDUCATION GLOBAL|\nLOWER DIVISION WRITING", text[start:])
        block = text[start:start + (nxt.start() if nxt else len(text))]
        cats[letter] = {
            "label": f"Category {letter}: {label}",
            "courses_required": int(req) if req else 1,
            "ccsf_courses": parse_course_table(block, prefixes, unknown),
        }

    writing_block = between(text, "LOWER DIVISION WRITING REQUIREMENT", "COURSES THAT FULFILL FOREIGN")
    writing = parse_course_table(writing_block.split("Courses Course Code", 1)[-1], prefixes, unknown)

    return cats, writing


def parse_foreign_language(path, prefixes):
    """
    The foreign language table has 4 columns (Level 1–4), and plain text loses which
    column a course is in (e.g. "FRENCH 3 FRENCH 4" is Level 3 and Level 4). So read
    word positions: each entry belongs to the column whose header is nearest.
    """
    levels = {f"level_{i}": [] for i in range(1, 5)}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            headers = [w for w in words if w["text"] == "Level"]
            if len(headers) < 4:
                continue
            cols = sorted(w["x0"] for w in headers[:4])
            top = headers[0]["top"]
            stop = min((w["top"] for w in words if w["text"] == "Note:" and w["top"] > top), default=1e9)
            rows = {}
            for w in words:
                if top + 5 < w["top"] < stop:
                    rows.setdefault(round(w["top"]), []).append(w)
            # An entry starts at a department name ("GERMAN") and runs until the next
            # one; its column is the header nearest to where the name starts. Names
            # start about 50pt left of their column's "Level" header.
            offset = 50
            dept_words = {n for n in prefixes if " " not in n}
            for _, ws in sorted(rows.items()):
                entries = []
                for w in sorted(ws, key=lambda w: w["x0"]):
                    if w["text"] in dept_words:
                        entries.append([w["x0"], [w["text"]]])
                    elif entries:
                        entries[-1][1].append(w["text"])
                for x0, texts in entries:
                    col = min(range(4), key=lambda i: abs(x0 + offset - cols[i]))
                    codes = to_codes(texts[0], " ".join(texts[1:]), prefixes)
                    if codes:
                        levels[f"level_{col + 1}"].append(" / ".join(codes))
            break
    return levels


# ── Part II: equivalences ─────────────────────────────────────────────────────

def parse_part2(text):
    block = between(text, "Course Name City College of San Francisco Courses USC Courses",
                    "PART III")
    flat = norm(block.split("USC Courses", 1)[1])
    # Long rows wrap: "PHYC 4B with PHYC 4BL with PHYC 4C with PHYS152 PHYSICS PHYC 4CL"
    # → "PHYC 4B with PHYC 4BL with PHYC 4C with PHYC 4CL PHYS152"
    flat = re.sub(r"((?:[A-Z]{2,5} \w+ with )+)([A-Z]{3,4}\d{3}[A-Z]?) [A-Z][A-Z ()]*? ([A-Z]{2,5} \d\w*)",
                  r"\1\3 \2", flat)
    equivs = []
    for m in re.finditer(
            r"((?:[A-Z]{2,5} \w+)(?: with [A-Z]{2,5} \w+)*) ((?:[A-Z]{3,4}\d{3}[A-Z]?)(?: and [A-Z]{3,4}\d{3}[A-Z]?)*)",
            flat):
        ccsf = [c.strip() for c in m.group(1).split(" with ")]
        usc = [re.sub(r"([A-Z]+)(\d)", r"\1 \2", u.strip()) for u in m.group(2).split(" and ")]
        item = {"ccsf_courses": ccsf, "usc_courses": usc, "requires_all": len(ccsf) > 1}
        if item not in equivs:
            equivs.append(item)
    return equivs


# ── Main ──────────────────────────────────────────────────────────────────────

def parse(path):
    text = pdf_text(path)
    period = re.search(r"Effective period:\s*(.+)", text)
    part3 = between(text, "Transfer department Courses which transfer for unit credit",
                    "PART IV")
    part4 = between(text, "Transfer department Courses that do not transfer", "PART V")
    names, transferable = parse_departments(part3)
    names4, non_transferable = parse_departments(part4)
    prefixes = {**names4, **names}
    unknown = set()
    cats, writing = parse_part1(text, prefixes, unknown)

    years = re.search(r"(Fall|Spring|Summer) (\d{4}) - (Fall|Spring|Summer) (\d{4})", period.group(1)) if period else None
    meta = {
        "source_file": Path(path).name,
        "academic_year": f"{years.group(2)}-{years.group(4)}" if years else None,
        "effective_period": norm(period.group(1)) if period else None,
        "from_institution": "City College of San Francisco",
        "to_institution": "University of Southern California",
        "agreement_type": "comprehensive",
        "notes": [
            "USC publishes one school-wide agreement per college; there are no major-specific agreements.",
            "Major-specific requirements must be checked on USC department websites.",
            "Students take 8 GE Core Literacy courses, but at least 2 must be taken at USC after enrolling.",
            "Courses not listed may still be appropriate for transfer in some instances.",
        ],
    }
    result = {
        "metadata": meta,
        "ge_requirements": {
            "core_literacy": {
                "description": "Students must take 8 courses from 6 GE Core Literacy areas "
                               "(at least 2 of them at USC after enrolling).",
                "categories": {CATEGORY_KEYS[k]: v for k, v in cats.items() if k in "ABCDEF"},
            },
            "global_perspectives": {
                "description": "May be fulfilled with transfer courses before entering USC or in summer "
                               "terms after starting USC. A course can count for one Global Perspective "
                               "and one Core Literacy category.",
                "categories": {CATEGORY_KEYS[k]: {"label": v["label"], "ccsf_courses": v["ccsf_courses"]}
                               for k, v in cats.items() if k in "GH"},
            },
            "writing_requirement": {
                "label": "Lower Division Writing Requirement",
                "description": "Equivalent to USC WRIT 130 / WRIT 150. Must be completed after high school "
                               "graduation and before starting at USC. Can't be taken pass/no pass.",
                "ccsf_courses": writing,
            },
            "foreign_language": {
                "label": "Foreign Language Requirement",
                "description": "Many majors require a third-semester foreign language course or equivalent "
                               "(International Relations: fourth). Must be taken in a classroom, not online.",
                "levels": parse_foreign_language(path, prefixes),
            },
        },
        "course_equivalences": parse_part2(text),
        "transferable": transferable,
        "transferable_code_definitions": CODE_FLAGS,
        "non_transferable": {p: sorted(n) for p, n in non_transferable.items()},
        "department_prefixes": dict(sorted(prefixes.items())),
        "_parse_warnings": sorted(f"Unknown department name in Part I: {u}" for u in unknown),
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 parser/parse_usc.py USC-Articulation_Agreement.pdf > USC_CCSF_agreement.json")
    print(json.dumps(parse(sys.argv[1]), indent=2, ensure_ascii=False))
