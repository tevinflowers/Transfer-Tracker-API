"""
ASSIST Articulation Agreement PDF Parser v3
CCSF → UC/CSU/Cal State PDFs → structured JSON

Usage:
  python parser/parse_assist.py path/to/*.pdf > all_agreements_v3.json

Column geometry (word x-coordinates):
  Left  (destination courses): x0 < 295
  Right (CCSF courses):        x0 >= 295
"""

import re, json, sys
from pathlib import Path
from collections import defaultdict
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ligatures import fix_ligatures  # noqa: E402  (repairs ff/ft ligature damage)

# ── Layout ───────────────────────────────────────────────────────────────────
DIVIDER_X = 295
Y_BAND    = 4

# ── Text constants ────────────────────────────────────────────────────────────
NO_ART = "No Course Articulated"
NEVER_ART = "This Course is Never Articulated"

SECTION_HEADERS = {
    # UCB style
    "REQUIRED COURSES FOR ADMISSION",
    "REQUIRED FOR ADMISSION",
    "LOWER DIVISION PREREQUISITES",
    "LOWER DIVISION REQUIREMENTS",
    "LOWER DIVISION MAJOR REQUIREMENTS",
    "STRONGLY RECOMMENDED COURSES",
    "SUGGESTED LOWER DIVISION MAJOR ELECTIVE COURSES",
    "TEST CREDIT", "EXAM CREDIT",
    # SFSU/UCD styles
    "REQUIRED MAJOR PREREQUISITE COURSES",
    "CORE REQUIREMENTS",
    "INTRODUCTORY ENGINEERING",
    "LOWER DIVISION MODULAR ELECTIVES",
    "ADDITIONAL REQUIREMENTS",
    "ADDITIONAL MAJOR PREPARATION COURSES",
    "MATHEMATICS AND SCIENCE COURSES",
    "PREPARATION COURSES FOR THE MAJOR",
    "UPPER DIVISION ARTICULATION",
    # UCD subject headers (used as section dividers)
    "BIOLOGICAL SCIENCE",
    "CHEMISTRY",
    "MATHEMATICS",
    "PHYSICS",
    "STATISTICS",
    "ENGINEERING",
    "COMPOSITION",
    # Emphasis/track sections
    "EMPHASIS IN ARCHITECTURAL HISTORY",
    "EMPHASIS IN MUSEUM STUDIES",
    "ART STUDIO COURSES",
    "QUANTITATIVE REASONING",
}

# Headers that are purely informational - skip them
INFO_HEADERS = {
    "GENERAL INFORMATION", "GRADE ADVISORY", "ASSOCIATE DEGREE FOR TRANSFER",
    "CATALOG", "CONTACT", "PROGRAM", "REQUIREMENTS", "THE MAJOR PROGRAM",
    "CAREER ALTERNATIVES", "ADMISSIONS INFORMATION",
    "SELECTIVE MAJOR REQUIREMENTS ADMISSIONS INFORMATION",
    "IMPORTANT MAJOR DETAILS", "IMPORTANT MAJOR INFORMATION",
    "TRANSFER ADMISSIONS GUARANTEE (TAG)", "TRANSFER ADMISSIONS GUARANTEE",
    "PROGRAMMING REQUIREMENT", "ADDITIONAL GE INFORMATION", "AP EXAM CREDIT",
    "PREPARATION NOTE", "EXAM CREDIT",
}

SKIP_RE = re.compile(
    r'^(https?://|Page \d+ of \d+|\d{4}-\d{4} .* Agreement|\d{1,2}/\d{1,2}/\d{2})',
    re.IGNORECASE
)

NOTE_KEYWORDS = [
    "effective next fall", "please refer to additional",
    "lab does not count", "minimum grade required",
    "recommended to be completed", "each community college course",
    "duplicate credit", "ap scores cannot", "same as ", "for more information",
    "http", "note:", "fall 202", "important", "required for admission",
    "articulates as a sequence", "complete entire sequence",
    "series is articulated in more than one",
    "course is articulated in more than one",
    "course not required for major",
    "content credit only", "no upper division credit",
    "recommended; not required",
    "not required for admission",
    "visit ", "contact ", "questions regarding",
    "at the time of", "group ",
]

AND_OR_RE   = re.compile(r'^(AND|OR)$', re.IGNORECASE)
SUBGRP_RE   = re.compile(r'^([A-F])$')
DIGIT_RE    = re.compile(r'^\d+$')
RULE_RE     = re.compile(r'^(Complete .+|Select .+)', re.IGNORECASE)
COURSE_RE   = re.compile(
    r'^([A-Z][A-Z0-9 /&]{0,20}?\d+[A-Z0-9]*(?:\s+[A-Z0-9]+)?)\s+(.+?)\s+(\d+\.\d+)$'
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def norm(s):
    return fix_ligatures(re.sub(r'\s+', ' ', s).strip())

def is_skip(t):
    return bool(SKIP_RE.match(t.strip()))

def is_note(t):
    tl = t.lower().strip()
    return any(k in tl for k in NOTE_KEYWORDS)

def try_course(text):
    t = norm(text)
    m = COURSE_RE.match(t)
    if m:
        return {"code": norm(m.group(1)), "title": norm(m.group(2)), "units": float(m.group(3))}
    m2 = re.match(r'^(.+?)\s+(\d+\.\d+)$', t)
    if m2:
        inner = norm(m2.group(1))
        cm = re.match(r'^([A-Z][A-Z0-9 /&]{0,20}?\d+[A-Z0-9]*)\s+(.+)', inner)
        if cm:
            return {"code": norm(cm.group(1)), "title": norm(cm.group(2)), "units": float(m2.group(2))}
    return None

def build_equiv(lines):
    clean = [norm(l) for l in lines if norm(l)]
    if not clean or all(l.upper() in (NO_ART.upper(), NEVER_ART.upper()) for l in clean):
        return {"articulated": False}
    options, cur = [], []
    for tok in clean:
        if tok.upper() == "OR":
            if cur: options.append(cur); cur = []
        elif tok.upper() == "AND":
            pass
        else:
            c = try_course(tok)
            if c: cur.append(c)
    if cur: options.append(cur)
    if not options:
        return {"articulated": False}
    if len(options) == 1:
        courses = options[0]
        return {"articulated": True,
                "logic": "single" if len(courses) == 1 else "AND",
                "courses": courses}
    return {"articulated": True, "logic": "OR",
            "options": [{"logic": "single" if len(g)==1 else "AND", "courses": g}
                        for g in options]}

# ── Row extraction ────────────────────────────────────────────────────────────

def get_rows(pdf_path):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for pg, page in enumerate(pdf.pages):
            words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
            bands = defaultdict(list)
            for w in words:
                bands[round(w["top"] / Y_BAND) * Y_BAND].append(w)
            for y in sorted(bands):
                ws = sorted(bands[y], key=lambda w: w["x0"])
                left  = " ".join(w["text"] for w in ws if w["x0"] <  DIVIDER_X).strip()
                right = " ".join(w["text"] for w in ws if w["x0"] >= DIVIDER_X).strip()
                rows.append({"page": pg+1, "y": y, "left": norm(left), "right": norm(right)})
    return rows

# ── Metadata ─────────────────────────────────────────────────────────────────

def get_meta(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        txt = pdf.pages[0].extract_text() or ""
    meta = {
        "source_file":      Path(pdf_path).name,
        "academic_year":    None,
        "date_published":   None,
        "major":            None,
        "degree_type":      None,
        "from_institution": "City College of San Francisco",
        "to_institution":   None,
    }
    m = re.search(r'(\d{4}-\d{4})', txt)
    if m: meta["academic_year"] = m.group(1)
    m = re.search(r'Date Published:\s*(\S+)', txt)
    if m: meta["date_published"] = m.group(1)

    # to_institution: look for "To: X" possibly on same line as "From:"
    # Match up to "From:" or end of line. The old [^F\n] class couldn't cross
    # a capital F, so "San Francisco State University" never matched (-> null).
    m = re.search(r'To:\s*(.+?)(?:\s+From:|\n|$)', txt)
    if m:
        meta["to_institution"] = norm(m.group(1))

    # major + degree from page text
    m = re.search(r'\n([A-Z][A-Za-z ,&:/]+?),\s*(B\.[AS]\.|M\.[AS]\.|A\.B\.)\s*\n', txt)
    if m:
        meta["major"]       = norm(m.group(1))
        meta["degree_type"] = m.group(2)
    else:
        dmap = {"BS":"B.S.","BA":"B.A.","MS":"M.S.","AA":"A.A.","AS":"A.S."}
        parts = Path(pdf_path).stem.split("_")
        mparts, deg = [], None
        for i, p in enumerate(parts):
            if i < 3: continue
            if p.upper() in dmap: deg = dmap[p.upper()]
            else: mparts.append(p)
        meta["major"]       = " ".join(mparts) or None
        meta["degree_type"] = deg
    return meta

# ── Main parse ────────────────────────────────────────────────────────────────

# ── Same-institution detection ────────────────────────────────────────────────

SAME_INST_PHRASES = [
    "complete entire sequence at same institution",
    "must be completed at the same community college",
    "you must complete all courses in a series at the same school",
    "all the courses in the series must be completed",
    "completed at the same community college",
]

SEQUENCE_ONLY_PHRASES = [
    "articulates as a sequence only",
    "as a sequence only",
    "series is articulated in more than one agreement",
    "course is articulated in more than one agreement",
]

def detect_flags(text):
    """Return (same_institution_required, sequence_only) booleans for a text string."""
    tl = text.lower()
    same = any(p in tl for p in SAME_INST_PHRASES)
    seq  = any(p in tl for p in SEQUENCE_ONLY_PHRASES)
    return same, seq


def parse_pdf(pdf_path):
    meta  = get_meta(pdf_path)
    rows  = get_rows(pdf_path)
    secs  = []
    cur_s = cur_g = cur_sg = None
    pending_group_num = None
    ubuf  = []
    cbuf  = []
    # Flags accumulated for the current row
    same_inst_flag = False
    seq_only_flag  = False
    # For handling title continuation lines
    last_left_had_course = False

    def flush():
        nonlocal ubuf, cbuf, same_inst_flag, seq_only_flag
        if not ubuf and not cbuf: return
        row = {
            "ucb_requirement":          build_equiv(ubuf),
            "ccsf_equivalent":          build_equiv(cbuf),
            "same_institution_required": same_inst_flag,
            "sequence_only":             seq_only_flag,
        }
        tgt = cur_sg or cur_g
        if tgt is not None:
            tgt.setdefault("articulation_rows", []).append(row)
        ubuf.clear(); cbuf.clear()
        same_inst_flag = False
        seq_only_flag  = False

    def set_sec(name):
        nonlocal cur_s, cur_g, cur_sg
        flush()
        # If already in this section (page-break continuation header), don't reset
        if cur_s and cur_s["section_name"] == name:
            return
        for s in secs:
            if s["section_name"] == name:
                cur_s = s; cur_g = None; cur_sg = None; return
        cur_s = {"section_name": name, "groups": []}
        secs.append(cur_s)
        cur_g = None; cur_sg = None

    def add_group(num, rule):
        nonlocal cur_g, cur_sg
        flush()
        g = {"group_number": num, "completion_rule": rule, "subgroups": []}
        if cur_s: cur_s["groups"].append(g)
        cur_g = g; cur_sg = None

    def add_subgroup(label):
        nonlocal cur_sg
        flush()
        sg = {"label": label, "articulation_rows": []}
        if cur_g: cur_g["subgroups"].append(sg)
        cur_sg = sg

    set_sec("GENERAL")

    for row in rows:
        L, R = row["left"], row["right"]
        if is_skip(L) and (is_skip(R) or not R): continue
        if not L and not R: continue
        if L == "END OF AGREEMENT": break

        up = L.upper()

        # ── Info/noise headers (skip silently) ───────────────────────────────
        if up in INFO_HEADERS and not R:
            continue

        # ── Section headers ───────────────────────────────────────────────────
        # Only trigger section change when not currently inside a group,
        # OR when it's a known top-level header that always starts a new section.
        TOP_LEVEL_HEADERS = {
            "REQUIRED COURSES FOR ADMISSION", "REQUIRED FOR ADMISSION",
            "LOWER DIVISION PREREQUISITES", "LOWER DIVISION REQUIREMENTS",
            "LOWER DIVISION MAJOR REQUIREMENTS", "STRONGLY RECOMMENDED COURSES",
            "SUGGESTED LOWER DIVISION MAJOR ELECTIVE COURSES",
            "TEST CREDIT", "EXAM CREDIT",
            "REQUIRED MAJOR PREREQUISITE COURSES", "CORE REQUIREMENTS",
            "INTRODUCTORY ENGINEERING", "LOWER DIVISION MODULAR ELECTIVES",
            "ADDITIONAL REQUIREMENTS", "ADDITIONAL MAJOR PREPARATION COURSES",
            "MATHEMATICS AND SCIENCE COURSES", "PREPARATION COURSES FOR THE MAJOR",
            "UPPER DIVISION ARTICULATION", "QUANTITATIVE REASONING",
            "EMPHASIS IN ARCHITECTURAL HISTORY", "EMPHASIS IN MUSEUM STUDIES",
            "ART STUDIO COURSES",
        }
        # Subject headers (CHEMISTRY, MATHEMATICS, etc.) are sub-sections within
        # a larger document — only use them as section dividers when not inside a group
        SUBJECT_HEADERS = {
            "BIOLOGICAL SCIENCE", "CHEMISTRY", "MATHEMATICS", "PHYSICS",
            "STATISTICS", "ENGINEERING", "COMPOSITION",
        }
        is_all_caps = (L == L.upper() and len(L) > 3)
        is_top = up in TOP_LEVEL_HEADERS
        is_subj = up in SUBJECT_HEADERS
        if is_all_caps and (is_top or (is_subj and cur_g is None)) and not R:
            set_sec(up); pending_group_num = None; continue

        # ── Combined section headers split across L+R (e.g. UCD) ─────────────
        combined = (up + " " + R.upper()).strip()
        if combined in SECTION_HEADERS:
            set_sec(combined); pending_group_num = None; continue
        if up in INFO_HEADERS and R.upper() in INFO_HEADERS:
            continue

        # ── Group: "1 Complete A, B, and C" (one line) ───────────────────────
        gm = re.match(r'^(\d+)\s+((?:Complete|Select) .+)$', L, re.IGNORECASE)
        if gm and not R:
            add_group(int(gm.group(1)), norm(gm.group(2))); continue

        # ── Group number alone (rule follows on next line) ────────────────────
        if DIGIT_RE.match(L) and not R:
            pending_group_num = int(L); continue

        # ── Completion rule ───────────────────────────────────────────────────
        rm = RULE_RE.match(L)
        if rm and not R and not try_course(L):
            rule = norm(rm.group(1))
            if pending_group_num is not None:
                add_group(pending_group_num, rule)
                pending_group_num = None
            elif cur_g:
                cur_g["completion_rule"] = rule
            continue

        # ── Subgroup letter ───────────────────────────────────────────────────
        if SUBGRP_RE.match(L) and not R:
            add_subgroup(L); continue

        # ── AND / OR tokens ───────────────────────────────────────────────────
        if AND_OR_RE.match(L) and not R:  ubuf.append(L); continue
        if AND_OR_RE.match(R) and not L:  cbuf.append(R); continue
        if AND_OR_RE.match(L) and AND_OR_RE.match(R):
            ubuf.append(L); cbuf.append(R); continue
        # OR token in center (both L and R empty, but OR visible)
        if not L and R.upper() in ("OR", "AND"):
            cbuf.append(R); continue

        # ── Notes — check for flags before dropping ───────────────────────────
        if is_note(L) and not try_course(L):
            if NO_ART.lower() in L.lower() or NEVER_ART.lower() in L.lower():
                cbuf.append(NO_ART)
            else:
                # Detect same-institution and sequence-only flags
                si, so = detect_flags(L)
                if si: same_inst_flag = True
                if so: seq_only_flag  = True
                # Also check right column
                si2, so2 = detect_flags(R)
                if si2: same_inst_flag = True
                if so2: seq_only_flag  = True
            continue
        if is_note(R) and not try_course(R) and not L:
            si, so = detect_flags(R)
            if si: same_inst_flag = True
            if so: seq_only_flag  = True
            continue

        # ── No Course Articulated in right col ────────────────────────────────
        if not L and (NO_ART.lower() in R.lower() or NEVER_ART.lower() in R.lower()):
            cbuf.append(NO_ART); continue

        # ── Course / continuation lines ───────────────────────────────────────
        L_is_course = bool(try_course(L)) or L.upper() in (NO_ART.upper(), NEVER_ART.upper())
        R_is_course = bool(try_course(R)) or R.upper() in (NO_ART.upper(), NEVER_ART.upper())

        # Title continuation: left has text but no units, right is empty,
        # and previous left line had a course => this is a wrapped title, skip it
        if L and not R and not L_is_course and not try_course(L):
            if ubuf and not AND_OR_RE.match(ubuf[-1]):
                # Might be a title continuation — if it doesn't look like
                # a section header or rule, just drop it
                if not RULE_RE.match(L) and L.upper() not in SECTION_HEADERS:
                    continue

        # New UCB course = flush previous row
        if L_is_course and ubuf:
            last = ubuf[-1].upper()
            if last not in ("AND", "OR"):
                flush()

        if L: ubuf.append(L)
        if R: cbuf.append(R)

    flush()

    secs = [s for s in secs
            if not (s["section_name"] == "GENERAL" and not s["groups"])]
    return {"metadata": meta, "requirement_sections": secs}

# ── CLI ───────────────────────────────────────────────────────────────────────

def main(paths):
    out = []
    for p in paths:
        print(f"Parsing: {Path(p).name}", file=sys.stderr)
        try:
            out.append(parse_pdf(p))
        except Exception as e:
            import traceback
            print(f"  ERROR {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    return out

if __name__ == "__main__":
    import glob
    paths = sys.argv[1:]
    if not paths:
        sys.exit("usage: python parser/parse_assist.py file1.pdf [file2.pdf ...]")
    # Expand globs for shells that don't (e.g. Windows cmd)
    paths = [q for p in paths for q in (sorted(glob.glob(p)) or [p])]
    print(json.dumps(main(paths), indent=2))
