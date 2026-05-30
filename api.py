"""
Transfer Tracker API
FastAPI server for the CCSF transfer tracking mobile app.

Endpoints:
  GET  /                          — health check
  GET  /schools                   — list all available schools
  GET  /majors?school=X           — list majors for a school
  GET  /agreements                — list all agreements (summary)
  GET  /agreements/{id}           — get one agreement by index
  POST /match                     — match courses against one agreement
  POST /compare                   — match courses against all agreements, ranked
  POST /compare/school/{school}   — match against one school only

Run locally:
  pip install fastapi uvicorn
  uvicorn api:app --reload

Then open: http://localhost:8000/docs  (interactive API explorer)
"""

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

def normalize_school(raw):
    return SCHOOL_ALIASES.get(raw.lower().strip(), raw.strip())

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
        "message": "CCSF Transfer Tracker API — visit /docs for interactive explorer",
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


@app.post("/match/usc/ge", tags=["USC"])
def match_usc_ge(body: MatchRequest):
    """
    Check which USC GE requirements a student's CCSF courses satisfy.
    Returns per-category completion for all 6 Core Literacy areas.
    """
    if not USC_AGREEMENT:
        raise HTTPException(status_code=503, detail="USC agreement data not loaded")

    from matcher import normalize_set
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
        from matcher import normalize_course
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
