"""
Transfer Tracker API
FastAPI server for the CCSF transfer tracking mobile app.

Endpoints:
  GET  /                          — health check
  GET  /schools                   — list all available schools
  GET  /majors?school=X           — list majors for a school
  GET  /agreements                — list all agreements (summary)
  GET  /agreements/{id}           — get one agreement by index
  POST /match/{id}                — match courses against one agreement
  POST /match/usc/ge              — check USC GE categories + course equivalences
  POST /compare                   — match courses against all agreements, ranked
  POST /compare/school/{school}   — match against one school only
  GET  /agreements/find?school=X&major=Y — find the agreement for a school + major
  GET  /courses?q=X               — search CCSF courses (autocomplete)
  POST /courses/check             — flag course codes that don't exist (typos)
  GET  /data-quality              — validator status for every agreement

Run locally:
  pip install fastapi uvicorn
  uvicorn api:app --reload

Then open: http://localhost:8000/docs  (interactive API explorer)
"""

import difflib
import re
from collections import Counter, defaultdict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os
import sys

# ── Load matcher ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from matcher import match_agreement, match_all

# ── Load data ─────────────────────────────────────────────────────────────────
DATA_PATH = os.environ.get('AGREEMENTS_JSON', 'all_agreements_v3.json')
USC_PATH  = os.environ.get('USC_JSON', 'USC_CCSF_agreement.json')

try:
    with open(DATA_PATH) as f:
        AGREEMENTS = json.load(f)
    print(f"✅ Loaded {len(AGREEMENTS)} agreements from {DATA_PATH}")
except FileNotFoundError:
    print(f"⚠️  Could not find {DATA_PATH} — starting with empty dataset")
    AGREEMENTS = []

try:
    with open(USC_PATH) as f:
        USC_AGREEMENT = json.load(f)
    print(f"✅ Loaded USC agreement from {USC_PATH}")
except FileNotFoundError:
    print(f"⚠️  Could not find {USC_PATH} — USC data unavailable")
    USC_AGREEMENT = None


# ── Data quality (parser/validate.py) ─────────────────────────────────────────
# Each agreement gets a status the app can show: "verified" (hand-checked),
# "auto-parsed" (no errors found) or "needs review" (don't trust its % yet).
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parser'))
    from validate import validate as _validate
    DATA_QUALITY = _validate(AGREEMENTS)
    print(f"✅ Validated agreements: {dict(Counter(r['status'] for r in DATA_QUALITY))}")
except Exception as e:  # never let the validator stop the API from starting
    print(f"⚠️  Validator unavailable ({e}); data_status will be 'unknown'")
    DATA_QUALITY = [None] * len(AGREEMENTS)

DATA_NOTES = {
    'verified':     'Checked by hand against the ASSIST agreement.',
    'auto-parsed':  'Read automatically from ASSIST; no problems found.',
    'needs review': 'This agreement may be incomplete or wrong. Check ASSIST.org before relying on it.',
    'unknown':      'Data quality not checked.',
}

def data_status(idx):
    q = DATA_QUALITY[idx] if 0 <= idx < len(DATA_QUALITY) else None
    status = q['status'] if q else 'unknown'
    return {'data_status': status, 'data_note': DATA_NOTES[status]}


# ── CCSF course catalog (from the CCSF side of every agreement) ──────────────

def _build_catalog():
    titles, units = defaultdict(Counter), {}
    for ag in AGREEMENTS:
        for s in ag.get('requirement_sections', []):
            for g in s.get('groups', []):
                rows = list(g.get('articulation_rows', []) or [])
                for sg in g.get('subgroups', []) or []:
                    rows += sg.get('articulation_rows', []) or []
                for r in rows:
                    side = r.get('ccsf_equivalent', {})
                    if not side.get('articulated'):
                        continue
                    for opt in side.get('options') or [side]:
                        for c in opt.get('courses', []):
                            code = re.sub(r'\s+', ' ', c.get('code', '').strip().upper())
                            if code:
                                titles[code][c.get('title') or ''] += 1
                                units.setdefault(code, c.get('units'))
    if USC_AGREEMENT:
        for cat in USC_AGREEMENT.get('ge_requirements', {}).get('core_literacy', {}).get('categories', {}).values():
            for entry in cat.get('ccsf_courses', []):
                for code in re.split(r'\s+with\s+', entry, flags=re.I):
                    code = re.sub(r'\s+', ' ', code.strip().upper())
                    if code and code not in titles:
                        titles[code][''] += 1
    catalog = {}
    for code, t in titles.items():
        # Prefer the longest of the most common titles (others may be cut off)
        best = max(t.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
        catalog[code] = {'code': code, 'title': best or None, 'units': units.get(code)}
    return catalog

CATALOG = _build_catalog()

def _split_code(code):
    m = re.match(r'^([A-Z&/ ]+?)\s*(\d.*)$', code)
    return (m.group(1).strip(), m.group(2).strip()) if m else (code, '')

# Older CCSF codes replaced by California common course numbering (C-numbers).
# Extend as needed; only add renames you've confirmed in the CCSF catalog.
RENAMED_CODES = {
    'ENGL 1A': 'ENGL C1000',
}

def suggest_codes(code, limit=3):
    """Likely intended CCSF codes for an unknown one (e.g. PHYS 4A → PHYC 4A)."""
    code = re.sub(r'\s+', ' ', code.strip().upper())
    if code in RENAMED_CODES:
        return [RENAMED_CODES[code]]
    prefix, number = _split_code(code)
    same_number = [c for c in CATALOG if _split_code(c)[1] == number and number]
    ranked = sorted(same_number, key=lambda c: -difflib.SequenceMatcher(None, prefix, _split_code(c)[0]).ratio())
    close = difflib.get_close_matches(code, CATALOG.keys(), n=limit, cutoff=0.75)
    out = []
    for c in ranked[:limit] + close:
        if c not in out and c != code:
            out.append(c)
    return out[:limit]


# ── School name normalization ─────────────────────────────────────────────────

SCHOOL_ALIASES = {
    'ucb': 'UC Berkeley',
    'uc berkeley': 'UC Berkeley',
    'berkeley': 'UC Berkeley',
    'ucd': 'UC Davis',
    'uc davis': 'UC Davis',
    'davis': 'UC Davis',
    'ucla': 'UCLA',
    'uc los angeles': 'UCLA',
    'sfsu': 'SFSU',
    'sf state': 'SFSU',
    'san francisco state': 'SFSU',
    'sjsu': 'SJSU',
    'san jose state': 'SJSU',
    'usc': 'USC',
    'southern california': 'USC',
}

# Keyword rules for the many ways the app may name a school, e.g.
# "UC Los Angeles (UCLA)", "University of California, Berkeley", "San Jose State University".
# CSU names are checked before UC ones so "Cal State LA" never becomes UCLA.
_SCHOOL_PATTERNS = [
    (r'san francisco state|\bsfsu\b|\bsf state\b', 'SFSU'),
    (r'san jos[eé] state|\bsjsu\b', 'SJSU'),
    (r'\bstate\b|\bcsu\b|cal state|polytechnic|cal poly', None),   # other CSUs: no alias
    (r'berkeley|\bucb\b', 'UC Berkeley'),
    (r'los angeles|\bucla\b', 'UCLA'),
    (r'\bdavis\b|\bucd\b', 'UC Davis'),
    (r'southern california|\busc\b', 'USC'),
]

def normalize_school(raw):
    """Map any reasonable school name to the name used in the data."""
    text = (raw or '').strip()
    if text.lower() in SCHOOL_ALIASES:
        return SCHOOL_ALIASES[text.lower()]
    low = text.lower()
    for pattern, school in _SCHOOL_PATTERNS:
        if re.search(pattern, low):
            return school or text
    return text


def normalize_major(raw):
    """Lowercase, '&' → 'and', drop punctuation and degree words, collapse spaces."""
    t = (raw or '').lower().replace('&', ' and ')
    t = re.sub(r'\b(b\.?\s?s|b\.?\s?a|a\.?\s?b|bs|ba)\.?$', ' ', t.strip())
    t = re.sub(r'[^a-z0-9 ]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def get_school(ag):
    """Extract normalized school name from an agreement."""
    m   = ag.get('metadata', {})
    src = m.get('source_file', '')
    dest = (m.get('to_institution') or '').lower()
    if 'berkeley' in dest:  return 'UC Berkeley'
    if 'davis' in dest:     return 'UC Davis'
    if 'angeles' in dest:   return 'UCLA'
    if 'sfsu' in src.lower() or 'san francisco state' in dest: return 'SFSU'
    if 'sjsu' in src.lower() or 'san jose state' in dest:      return 'SJSU'
    return m.get('to_institution') or 'Unknown'

def agreement_summary(ag, idx):
    """Return a lightweight summary of an agreement (no full section data)."""
    m = ag.get('metadata', {})
    return {
        'id':           idx,
        'school':       get_school(ag),
        'major':        m.get('major'),
        'degree_type':  m.get('degree_type'),
        'academic_year': m.get('academic_year'),
        'source_file':  m.get('source_file'),
        **data_status(idx),
    }


# ── Request/Response models ───────────────────────────────────────────────────

class MatchRequest(BaseModel):
    completed_courses:   list[str]
    in_progress_courses: list[str] = []

class CompareRequest(BaseModel):
    completed_courses:   list[str]
    in_progress_courses: list[str] = []
    min_progress:        float = 0.0   # 0.0–1.0, filter out agreements below this
    section_filter:      Optional[str] = None  # e.g. "REQUIRED COURSES FOR ADMISSION"

class MatchResult(BaseModel):
    agreement:  dict
    student:    dict
    overall:    dict
    sections:   list
    warnings:   list

class CourseCheckRequest(BaseModel):
    codes: list[str]

class AgreementSummary(BaseModel):
    id:           int
    school:       str
    major:        Optional[str]
    degree_type:  Optional[str]
    academic_year: Optional[str]
    source_file:  Optional[str]


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CCSF Transfer Tracker API",
    description="Match CCSF courses against articulation agreements for UC, CSU, and USC.",
    version="1.0.0",
)

# Allow mobile app and web clients to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Lock down to your app's domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "agreements_loaded": len(AGREEMENTS),
        "usc_loaded": USC_AGREEMENT is not None,
        "message": "CCSF Transfer Tracker API - visit /docs for interactive explorer",
    }


@app.get("/schools", tags=["Browse"])
def list_schools():
    """List all schools with agreement counts."""
    from collections import Counter
    counts = Counter(get_school(ag) for ag in AGREEMENTS)
    if USC_AGREEMENT:
        counts['USC'] = 1
    return {
        "schools": [
            {"name": school, "agreement_count": count}
            for school, count in sorted(counts.items())
        ]
    }


@app.get("/majors", tags=["Browse"])
def list_majors(school: Optional[str] = Query(None, description="Filter by school name")):
    """List all majors, optionally filtered by school."""
    results = []
    for idx, ag in enumerate(AGREEMENTS):
        ag_school = get_school(ag)
        if school and normalize_school(school) != ag_school:
            continue
        results.append(agreement_summary(ag, idx))

    if not results:
        raise HTTPException(status_code=404,
            detail=f"No agreements found for school '{school}'")
    return {"count": len(results), "agreements": results}


@app.get("/agreements", tags=["Browse"])
def list_agreements(
    school: Optional[str] = Query(None),
    degree_type: Optional[str] = Query(None, description="e.g. B.S. or B.A."),
):
    """List all agreements with optional filters."""
    results = []
    for idx, ag in enumerate(AGREEMENTS):
        m = ag.get('metadata', {})
        if school and normalize_school(school) != get_school(ag):
            continue
        if degree_type and degree_type.upper() != (m.get('degree_type') or '').upper():
            continue
        results.append(agreement_summary(ag, idx))
    return {"count": len(results), "agreements": results}


@app.get("/agreements/find", tags=["Browse"])
def find_agreement(
    school: str = Query(..., description="School name, e.g. 'UC Berkeley', 'UC Los Angeles (UCLA)', 'San Jose State University'"),
    major: str = Query(..., description="Major name, e.g. 'Bioengineering'"),
):
    """
    Find the agreement for a school + major.

    `agreements` contains ONLY exact major matches (ignoring case, punctuation, '&'
    vs 'and' and degree letters). Use agreements[0] when it isn't empty.

    If it's empty there's no data for that school + major. The app must show
    "no data yet" (never complete). `suggestions` lists similar majors at that school
    ("Engineering" → "Aerospace Engineering", "Bioengineering", …) to offer as
    "Did you mean…?". Never use a suggestion without the student choosing it.
    """
    school_n = normalize_school(school)
    want = normalize_major(major)
    exact, suggestions = [], []
    at_school = [(idx, ag) for idx, ag in enumerate(AGREEMENTS) if get_school(ag) == school_n]
    for idx, ag in at_school:
        have = normalize_major(ag.get('metadata', {}).get('major'))
        if have and have == want:
            exact.append(agreement_summary(ag, idx))
    if not exact and want:
        want_words = set(want.split())
        scored = []
        for idx, ag in at_school:
            have = normalize_major(ag.get('metadata', {}).get('major'))
            if not have:
                continue
            overlap = len(want_words & set(have.split()))
            ratio = difflib.SequenceMatcher(None, want, have).ratio()
            if overlap or ratio >= 0.6 or want in have or have in want:
                scored.append((-(overlap + ratio), agreement_summary(ag, idx)))
        suggestions = [summary for _, summary in sorted(scored, key=lambda t: t[0])[:5]]
    out = {
        "school": school_n,
        "school_has_data": bool(at_school),
        "major": major,
        "count": len(exact),
        "agreements": exact,
        "suggestions": suggestions,
    }
    if not exact:
        where = school_n if at_school else f"{school_n} (no agreements for this school yet)"
        out["message"] = (f"No {where} {major} agreement yet. Show this as 'no data yet' "
                          f"(never as complete).")
    return out


@app.get("/agreements/{agreement_id}", tags=["Browse"])
def get_agreement(agreement_id: int):
    """Get full details of one agreement by its ID."""
    if agreement_id < 0 or agreement_id >= len(AGREEMENTS):
        raise HTTPException(status_code=404, detail="Agreement not found")
    ag  = AGREEMENTS[agreement_id]
    out = agreement_summary(ag, agreement_id)
    out['sections'] = ag.get('requirement_sections', [])
    return out


@app.post("/match/{agreement_id}", tags=["Match"], response_model=MatchResult)
def match_one(agreement_id: int, body: MatchRequest):
    """
    Match a student's courses against one specific agreement.

    Returns full section/group/row breakdown with completion status,
    progress percentages, and warnings (same-institution rules, etc.)
    """
    if agreement_id < 0 or agreement_id >= len(AGREEMENTS):
        raise HTTPException(status_code=404, detail="Agreement not found")

    result = match_agreement(
        AGREEMENTS[agreement_id],
        body.completed_courses,
        body.in_progress_courses,
    )
    result['agreement'].update(id=agreement_id, **data_status(agreement_id))
    return result


@app.post("/compare", tags=["Match"])
def compare_all(body: CompareRequest):
    """
    Match a student's courses against ALL agreements, ranked by completion.

    Returns agreements sorted from most to least complete.
    Use min_progress to filter out agreements with very low completion.
    Use section_filter to focus on a specific requirement section.
    """
    results = match_all(
        AGREEMENTS,
        body.completed_courses,
        body.in_progress_courses,
        min_progress=body.min_progress,
        section_filter=body.section_filter,
    )

    # Return lightweight summary version for the compare view
    summaries = []
    for r in results:
        summaries.append({
            'agreement':    r['agreement'],
            'overall':      r['overall'],
            'warning_count': len(r['warnings']),
        })

    return {
        "count": len(summaries),
        "completed_courses": body.completed_courses,
        "in_progress_courses": body.in_progress_courses,
        "agreements": summaries,
    }


@app.post("/compare/school/{school}", tags=["Match"])
def compare_school(school: str, body: CompareRequest):
    """
    Match a student's courses against all agreements for one school.

    Returns full match results (not just summaries) for deeper inspection.
    """
    school_normalized = normalize_school(school)
    filtered = [ag for ag in AGREEMENTS if get_school(ag) == school_normalized]

    if not filtered:
        raise HTTPException(status_code=404,
            detail=f"No agreements found for school '{school}'. "
                   f"Available: UC Berkeley, UC Davis, UCLA, SFSU, SJSU, USC")

    results = match_all(
        filtered,
        body.completed_courses,
        body.in_progress_courses,
        min_progress=body.min_progress,
        section_filter=body.section_filter,
    )

    return {
        "school":            school_normalized,
        "count":             len(results),
        "completed_courses": body.completed_courses,
        "in_progress_courses": body.in_progress_courses,
        "agreements":        results,
    }


@app.get("/courses", tags=["Courses"])
def search_courses(q: str = Query("", description="Code or title text, e.g. 'phyc 4', 'calculus'"),
                   limit: int = Query(20, ge=1, le=100)):
    """
    Search CCSF courses that appear in the agreements, for autocomplete on the course
    form. Matches the start of the code first, then anywhere in the code or title.
    """
    term = re.sub(r'\s+', ' ', q.strip().upper())
    if not term:
        items = sorted(CATALOG.values(), key=lambda c: c['code'])
    else:
        starts = [c for c in CATALOG.values() if c['code'].startswith(term)]
        contains = [c for c in CATALOG.values() if c not in starts and
                    (term in c['code'] or term in (c['title'] or '').upper())]
        items = sorted(starts, key=lambda c: c['code']) + sorted(contains, key=lambda c: c['code'])
    return {"count": len(items[:limit]), "total_courses": len(CATALOG), "courses": items[:limit]}


@app.post("/courses/check", tags=["Courses"])
def check_courses(body: CourseCheckRequest):
    """
    Check course codes before saving. Codes that appear in no agreement come back in
    `unknown` with suggestions, e.g. PHYS 4A → PHYC 4A.
    """
    known, unknown = [], []
    for raw in body.codes:
        code = re.sub(r'\s+', ' ', raw.strip().upper())
        if code in CATALOG:
            known.append(CATALOG[code])
        else:
            unknown.append({"code": raw, "suggestions": suggest_codes(code)})
    return {
        "known": known,
        "unknown": unknown,
        "note": ("Unknown codes don't appear in any agreement. That may be a typo (see "
                 "suggestions), an old course code, or a course that just doesn't count "
                 "toward these agreements. Let the student keep it, but show the suggestions."),
    }


@app.get("/data-quality", tags=["Browse"])
def data_quality(status: Optional[str] = Query(None, description="verified, auto-parsed or needs review")):
    """Validator status for every agreement (see parser/validate.py)."""
    rows = []
    for idx, ag in enumerate(AGREEMENTS):
        q = DATA_QUALITY[idx]
        s = data_status(idx)
        if status and s['data_status'] != status:
            continue
        rows.append({**agreement_summary(ag, idx),
                     'errors': [i['message'] for i in (q or {}).get('issues', []) if i['level'] == 'error']})
    counts = Counter(data_status(i)['data_status'] for i in range(len(AGREEMENTS)))
    return {"counts": dict(counts), "count": len(rows), "agreements": rows}


@app.post("/match/usc/ge", tags=["USC"])
def match_usc_ge(body: MatchRequest):
    """
    Check which USC GE requirements a student's CCSF courses satisfy.
    Returns per-category completion for all 6 Core Literacy areas.
    """
    if not USC_AGREEMENT:
        raise HTTPException(status_code=503, detail="USC agreement data not loaded")

    from matcher import normalize_set, normalize_course
    completed   = normalize_set(body.completed_courses)
    in_progress = normalize_set(body.in_progress_courses)

    categories = USC_AGREEMENT['ge_requirements']['core_literacy']['categories']
    results = {}

    for cat_key, cat in categories.items():
        cat_courses = [c.split()[0] + ' ' + ' '.join(c.split()[1:])
                       if len(c.split()) > 1 else c
                       for c in cat.get('ccsf_courses', [])]

        # Handle "X with Y" style (need both)
        satisfied = []
        for entry in cat.get('ccsf_courses', []):
            if ' with ' in entry.lower():
                parts = [p.strip() for p in entry.lower().split(' with ')]
                if all(p.upper() in completed for p in parts):
                    satisfied.append(entry)
            else:
                if entry.upper() in completed:
                    satisfied.append(entry)

        in_prog = []
        for entry in cat.get('ccsf_courses', []):
            if entry.upper() in in_progress:
                in_prog.append(entry)

        needed = cat.get('courses_required', 1)
        status = (
            'complete'    if len(satisfied) >= needed else
            'in_progress' if (satisfied or in_prog) else
            'not_started'
        )

        results[cat_key] = {
            'label':            cat['label'],
            'courses_required': needed,
            'status':           status,
            'satisfied_by':     satisfied,
            'in_progress':      in_prog,
        }

    # Writing requirement
    writing = USC_AGREEMENT['ge_requirements']['writing_requirement']
    writing_done = [c for c in writing['ccsf_courses'] if c.upper() in completed]
    writing_prog = [c for c in writing['ccsf_courses'] if c.upper() in in_progress]

    # Course equivalences (Part II)
    equiv = USC_AGREEMENT['course_equivalences']
    matched_equiv = []
    for eq in equiv:
        ccsf_needed = [normalize_course(c) for c in eq['ccsf_courses']]
        if eq.get('requires_all'):
            if all(c in completed for c in ccsf_needed):
                matched_equiv.append({
                    'ccsf_courses': eq['ccsf_courses'],
                    'usc_courses':  eq['usc_courses'],
                })
        else:
            if any(c in completed for c in ccsf_needed):
                matched_equiv.append({
                    'ccsf_courses': eq['ccsf_courses'],
                    'usc_courses':  eq['usc_courses'],
                })

    total_cats = len(results)
    complete_cats = sum(1 for r in results.values() if r['status'] == 'complete')

    return {
        'school': 'USC',
        'overall': {
            'ge_categories_complete': complete_cats,
            'ge_categories_total':    total_cats,
            'writing_satisfied':      bool(writing_done),
            'course_equivalences_matched': len(matched_equiv),
        },
        'ge_categories':    results,
        'writing_requirement': {
            'label':       writing['label'],
            'status':      'complete' if writing_done else
                           'in_progress' if writing_prog else 'not_started',
            'satisfied_by': writing_done,
        },
        'course_equivalences': matched_equiv,
    }


# ── Dev server ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
