"""
Transfer Requirement Matcher
Core logic for the CCSF transfer tracking app.

Given:
  - A student's completed CCSF courses (list of course codes)
  - An articulation agreement (from all_agreements_v3.json)

Returns:
  - Per-section completion status
  - Per-group completion status  
  - Per-row completion status (with progress tracking for series)
  - Overall completion percentage
  - Warnings (same_institution_required, in-progress series, etc.)

Usage:
  from matcher import match_agreement
  result = match_agreement(agreement, completed_courses, in_progress_courses)
"""

import re
import json
from pathlib import Path


# ── Course normalization ──────────────────────────────────────────────────────

def normalize_course(code):
    """Normalize a course code for comparison: uppercase, collapse spaces."""
    return re.sub(r'\s+', ' ', code.strip().upper())

def normalize_set(courses):
    return {normalize_course(c) for c in courses}


# ── Completion rule parser ────────────────────────────────────────────────────

def parse_completion_rule(rule):
    """
    Parse a completion rule string into structured logic.
    Returns dict with:
      subgroup_logic: 'AND' | 'OR'  — how subgroups relate to each other
      min_count: int | None          — minimum subgroups/courses to satisfy
      is_units: bool                 — True if min_count is a unit count
    """
    r = (rule or '').lower().strip().rstrip('.')

    # Extract numeric requirement
    num_match = re.search(r'(\d+(?:\.\d+)?)\s*(course|sequence|units|from|up to)', r)
    min_count = float(num_match.group(1)) if num_match else None
    is_units  = bool(num_match and 'unit' in num_match.group(2))

    # Determine subgroup relationship
    has_or  = bool(re.search(r'\bor\b', r))
    has_and = bool(re.search(r'\band\b', r))

    if 'the following' in r and not min_count:
        # "Complete the following" — all subgroups/rows required
        subgroup_logic = 'AND'
    elif min_count and not is_units:
        # "Complete N courses/sequences from..." — pick N
        subgroup_logic = 'OR'
    elif has_or and not has_and:
        subgroup_logic = 'OR'
    elif has_and and not has_or:
        subgroup_logic = 'AND'
    elif has_or:
        # Mixed like "A, B, or C" — OR wins
        subgroup_logic = 'OR'
    else:
        subgroup_logic = 'AND'

    return {
        'subgroup_logic': subgroup_logic,
        'min_count': int(min_count) if min_count and not is_units else None,
        'is_units': is_units,
    }


# ── Row-level matching ────────────────────────────────────────────────────────

def match_ccsf_equiv(ccsf_equiv, completed, in_progress):
    """
    Check whether a student satisfies a single CCSF equivalency block.

    Returns dict:
      status: 'complete' | 'in_progress' | 'not_started' | 'not_articulated'
      satisfied_by: list of course codes that satisfy this
      courses_needed: list of courses still needed
      courses_completed: list of completed courses in this block
      courses_in_progress: list of in-progress courses in this block
    """
    if not ccsf_equiv.get('articulated'):
        return {
            'status': 'not_articulated',
            'satisfied_by': [],
            'courses_needed': [],
            'courses_completed': [],
            'courses_in_progress': [],
        }

    logic = ccsf_equiv.get('logic', 'single')

    if logic in ('single', 'AND'):
        courses = ccsf_equiv.get('courses', [])
        return _check_course_list(courses, completed, in_progress)

    elif logic == 'OR':
        # Try each option — return the best one (most progress)
        options = ccsf_equiv.get('options', [])
        best = None
        for opt in options:
            result = _check_course_list(opt.get('courses', []), completed, in_progress)
            if best is None:
                best = result
            elif _status_rank(result['status']) > _status_rank(best['status']):
                best = result
            elif (result['status'] == best['status'] and
                  len(result['courses_completed']) > len(best['courses_completed'])):
                best = result
        return best or {
            'status': 'not_started',
            'satisfied_by': [],
            'courses_needed': [],
            'courses_completed': [],
            'courses_in_progress': [],
        }

    return {
        'status': 'not_started',
        'satisfied_by': [],
        'courses_needed': [],
        'courses_completed': [],
        'courses_in_progress': [],
    }


def _check_course_list(courses, completed, in_progress):
    """Check a list of courses that must ALL be completed (AND logic)."""
    done, prog, needed = [], [], []

    for c in courses:
        code = normalize_course(c['code'])
        if code in completed:
            done.append(c['code'])
        elif code in in_progress:
            prog.append(c['code'])
        else:
            needed.append(c['code'])

    if not needed and not prog:
        status = 'complete'
    elif done or prog:
        status = 'in_progress'
    else:
        status = 'not_started'

    return {
        'status': status,
        'satisfied_by': done,
        'courses_needed': needed,
        'courses_completed': done,
        'courses_in_progress': prog,
    }


def _status_rank(status):
    return {'complete': 3, 'in_progress': 2, 'not_started': 1, 'not_articulated': 0}[status]


# ── Row-level result ──────────────────────────────────────────────────────────

def match_row(row, completed, in_progress):
    """
    Match a single articulation row.
    Returns the row result with completion status and any warnings.
    """
    ucb  = row['ucb_requirement']
    ccsf = row['ccsf_equivalent']

    ccsf_result = match_ccsf_equiv(ccsf, completed, in_progress)

    warnings = []
    if row.get('same_institution_required') and ccsf_result['status'] in ('complete', 'in_progress'):
        warnings.append({
            'type': 'same_institution_required',
            'message': 'These courses must be completed at the same community college to count as a series.'
        })
    if row.get('sequence_only') and ccsf_result['status'] == 'in_progress':
        warnings.append({
            'type': 'sequence_only',
            'message': 'Credit only applies when the full series is complete — partial completion does not count.'
        })

    # Build destination requirement label
    dest_label = _format_requirement(ucb)

    return {
        'destination_requirement': dest_label,
        'ccsf_equivalent': _format_requirement(ccsf) if ccsf.get('articulated') else None,
        'status': ccsf_result['status'],
        'courses_completed': ccsf_result['courses_completed'],
        'courses_in_progress': ccsf_result['courses_in_progress'],
        'courses_needed': ccsf_result['courses_needed'],
        'same_institution_required': row.get('same_institution_required', False),
        'sequence_only': row.get('sequence_only', False),
        'warnings': warnings,
    }


def _format_requirement(equiv):
    """Format an equivalency block as a human-readable string."""
    if not equiv.get('articulated'):
        return 'No Course Articulated'
    logic = equiv.get('logic', 'single')
    if logic in ('single', 'AND'):
        return ' + '.join(c['code'] for c in equiv.get('courses', []))
    elif logic == 'OR':
        return ' OR '.join(
            ' + '.join(c['code'] for c in opt.get('courses', []))
            for opt in equiv.get('options', [])
        )
    return '?'


# ── Subgroup-level matching ───────────────────────────────────────────────────

def match_subgroup(subgroup, completed, in_progress):
    """
    Match all rows in a subgroup.
    All rows in a subgroup are requirements that must ALL be met (AND within subgroup).
    Returns subgroup result with per-row breakdown.
    """
    rows = subgroup.get('articulation_rows', [])
    row_results = [match_row(r, completed, in_progress) for r in rows]

    # A subgroup is complete only if every row is complete or not_articulated
    # (not_articulated rows don't block completion)
    blocking_rows = [r for r in row_results if r['status'] not in ('complete', 'not_articulated')]
    complete_rows = [r for r in row_results if r['status'] == 'complete']
    articulated_rows = [r for r in row_results if r['status'] != 'not_articulated']

    if not articulated_rows:
        status = 'not_articulated'
    elif not blocking_rows:
        status = 'complete'
    elif complete_rows or any(r['status'] == 'in_progress' for r in row_results):
        status = 'in_progress'
    else:
        status = 'not_started'

    # Progress fraction: complete rows / articulated rows
    progress = len(complete_rows) / len(articulated_rows) if articulated_rows else 0.0

    return {
        'label': subgroup.get('label', ''),
        'status': status,
        'progress': round(progress, 3),
        'rows': row_results,
        'warnings': [w for r in row_results for w in r.get('warnings', [])],
    }


# ── Group-level matching ──────────────────────────────────────────────────────

def match_group(group, completed, in_progress):
    """
    Match a requirement group, respecting its completion_rule logic.
    """
    rule_parsed = parse_completion_rule(group.get('completion_rule', ''))
    subgroup_logic = rule_parsed['subgroup_logic']
    min_count      = rule_parsed['min_count']

    subgroups    = group.get('subgroups', [])
    direct_rows  = group.get('articulation_rows', [])

    # Match all subgroups
    sg_results = [match_subgroup(sg, completed, in_progress) for sg in subgroups]

    # Match direct rows (groups without subgroups)
    direct_results = [match_row(r, completed, in_progress) for r in direct_rows]

    # Determine group status based on completion rule
    if sg_results:
        complete_sgs = [sg for sg in sg_results if sg['status'] == 'complete']
        articulated_sgs = [sg for sg in sg_results if sg['status'] != 'not_articulated']

        if subgroup_logic == 'AND':
            # All subgroups must be complete
            blocking = [sg for sg in sg_results
                        if sg['status'] not in ('complete', 'not_articulated')]
            if not blocking and articulated_sgs:
                status = 'complete'
            elif complete_sgs or any(sg['status'] == 'in_progress' for sg in sg_results):
                status = 'in_progress'
            else:
                status = 'not_started'
            # Progress = fraction of AND subgroups complete
            progress = len(complete_sgs) / len(articulated_sgs) if articulated_sgs else 0.0

        else:  # OR logic
            needed = min_count or 1
            if len(complete_sgs) >= needed:
                status = 'complete'
                progress = 1.0
            elif complete_sgs or any(sg['status'] == 'in_progress' for sg in sg_results):
                status = 'in_progress'
                # Progress = best single subgroup progress
                progress = max((sg['progress'] for sg in sg_results), default=0.0)
            else:
                status = 'not_started'
                progress = 0.0

    elif direct_results:
        # Direct rows — all must be complete (AND)
        articulated = [r for r in direct_results if r['status'] != 'not_articulated']
        complete    = [r for r in direct_results if r['status'] == 'complete']
        blocking    = [r for r in articulated if r['status'] != 'complete']

        if not blocking and articulated:
            status = 'complete'
        elif complete or any(r['status'] == 'in_progress' for r in direct_results):
            status = 'in_progress'
        else:
            status = 'not_started'

        progress = len(complete) / len(articulated) if articulated else 0.0

    else:
        status = 'not_started'
        progress = 0.0

    return {
        'group_number': group.get('group_number'),
        'completion_rule': group.get('completion_rule', ''),
        'subgroup_logic': subgroup_logic,
        'status': status,
        'progress': round(progress, 3),
        'subgroups': sg_results,
        'direct_rows': direct_results,
        'warnings': [w for sg in sg_results for w in sg.get('warnings', [])] +
                    [w for r in direct_results for w in r.get('warnings', [])],
    }


# ── Section-level matching ────────────────────────────────────────────────────

def match_section(section, completed, in_progress):
    """Match all groups in a section."""
    groups = section.get('groups', [])
    group_results = [match_group(g, completed, in_progress) for g in groups]

    articulated_groups = [g for g in group_results if g['status'] != 'not_articulated']
    complete_groups    = [g for g in group_results if g['status'] == 'complete']

    if not articulated_groups:
        status   = 'not_articulated'
        progress = 0.0
    elif len(complete_groups) == len(articulated_groups):
        status   = 'complete'
        progress = 1.0
    elif complete_groups or any(g['status'] == 'in_progress' for g in group_results):
        status   = 'in_progress'
        progress = (sum(g['progress'] for g in articulated_groups) /
                    len(articulated_groups))
    else:
        status   = 'not_started'
        progress = 0.0

    return {
        'section_name': section.get('section_name', ''),
        'status': status,
        'progress': round(progress, 3),
        'groups': group_results,
        'warnings': [w for g in group_results for w in g.get('warnings', [])],
    }


# ── Top-level agreement match ─────────────────────────────────────────────────

def match_agreement(agreement, completed_courses, in_progress_courses=None):
    """
    Main entry point.

    Args:
        agreement: single agreement dict from all_agreements_v3.json
        completed_courses: list of CCSF course codes the student has completed
                           e.g. ["MATH 110A", "MATH 110B", "PHYC 4A", "PHYC 4AL"]
        in_progress_courses: list of CCSF course codes currently being taken
                             e.g. ["MATH 110C"]

    Returns:
        Full match result with section/group/row breakdown and overall stats
    """
    completed   = normalize_set(completed_courses or [])
    in_progress = normalize_set(in_progress_courses or [])

    sections = agreement.get('requirement_sections', [])
    section_results = [match_section(s, completed, in_progress) for s in sections]

    # Overall stats
    all_groups = [g for s in section_results for g in s['groups']]
    articulated = [g for g in all_groups if g['status'] != 'not_articulated']
    complete    = [g for g in all_groups if g['status'] == 'complete']

    if not articulated:
        overall_progress = 0.0
        overall_status   = 'not_articulated'
    elif len(complete) == len(articulated):
        overall_progress = 1.0
        overall_status   = 'complete'
    else:
        overall_progress = (sum(g['progress'] for g in articulated) /
                           len(articulated))
        if complete or any(g['status'] == 'in_progress' for g in articulated):
            overall_status = 'in_progress'
        else:
            overall_status = 'not_started'

    # Collect all warnings
    all_warnings = [w for s in section_results for w in s.get('warnings', [])]

    meta = agreement.get('metadata', {})

    return {
        'agreement': {
            'major': meta.get('major'),
            'degree_type': meta.get('degree_type'),
            'to_institution': meta.get('to_institution'),
            'academic_year': meta.get('academic_year'),
            'source_file': meta.get('source_file'),
        },
        'student': {
            'completed_courses': sorted(completed_courses or []),
            'in_progress_courses': sorted(in_progress_courses or []),
        },
        'overall': {
            'status': overall_status,
            'progress': round(overall_progress, 3),
            'progress_pct': round(overall_progress * 100, 1),
            'groups_complete': len(complete),
            'groups_total': len(articulated),
        },
        'sections': section_results,
        'warnings': all_warnings,
    }


# ── Convenience: match against all agreements ─────────────────────────────────

def match_all(agreements, completed_courses, in_progress_courses=None,
              min_progress=0.0, school_filter=None, section_filter=None):
    """
    Match a student's courses against multiple agreements.

    Args:
        agreements: list of agreements from all_agreements_v3.json
        completed_courses: list of completed CCSF course codes
        in_progress_courses: list of in-progress CCSF course codes
        min_progress: only return agreements where progress >= this (0.0–1.0)
        school_filter: only include agreements for this school name (partial match)
        section_filter: only include this section name in results
                        e.g. 'REQUIRED COURSES FOR ADMISSION'

    Returns:
        List of match results sorted by overall progress descending
    """
    results = []
    for ag in agreements:
        # Optional school filter
        if school_filter:
            dest = (ag.get('metadata', {}).get('to_institution') or '').lower()
            src  = (ag.get('metadata', {}).get('source_file') or '').lower()
            if school_filter.lower() not in dest and school_filter.lower() not in src:
                continue

        result = match_agreement(ag, completed_courses, in_progress_courses)

        if result['overall']['progress'] >= min_progress:
            # Optional section filter
            if section_filter:
                result['sections'] = [
                    s for s in result['sections']
                    if section_filter.lower() in s['section_name'].lower()
                ]
            results.append(result)

    results.sort(key=lambda r: r['overall']['progress'], reverse=True)
    return results


# ── Summary formatter ─────────────────────────────────────────────────────────

def format_summary(result):
    """Print a human-readable summary of a match result."""
    ag   = result['agreement']
    ov   = result['overall']
    stu  = result['student']

    lines = [
        f"\n{'='*60}",
        f"  {ag['major']} {ag['degree_type']}",
        f"  → {ag['to_institution']}",
        f"  Academic year: {ag['academic_year']}",
        f"{'='*60}",
        f"  Student completed: {', '.join(stu['completed_courses']) or 'none'}",
        f"  In progress:       {', '.join(stu['in_progress_courses']) or 'none'}",
        f"{'─'*60}",
        f"  Overall: {ov['progress_pct']}%  "
        f"({ov['groups_complete']}/{ov['groups_total']} requirement groups complete)",
        f"  Status:  {ov['status'].upper()}",
        f"{'─'*60}",
    ]

    STATUS_ICON = {
        'complete':       '✅',
        'in_progress':    '🔄',
        'not_started':    '⬜',
        'not_articulated':'➖',
    }

    for sec in result['sections']:
        pct = round(sec['progress'] * 100)
        icon = STATUS_ICON.get(sec['status'], '?')
        lines.append(f"\n  {icon} {sec['section_name']}  ({pct}%)")

        for g in sec['groups']:
            g_icon = STATUS_ICON.get(g['status'], '?')
            g_pct  = round(g['progress'] * 100)
            lines.append(f"    {g_icon} Group {g['group_number']}: "
                         f"{g['completion_rule']}  ({g_pct}%)")

            # Show subgroup detail
            for sg in g['subgroups']:
                sg_icon = STATUS_ICON.get(sg['status'], '?')
                lines.append(f"      {sg_icon} [{sg['label']}]")
                for row in sg['rows']:
                    r_icon = STATUS_ICON.get(row['status'], '?')
                    dest   = row['destination_requirement']
                    ccsf   = row['ccsf_equivalent'] or 'No Articulation'
                    lines.append(f"        {r_icon} {dest:35} ← {ccsf}")
                    if row['courses_completed']:
                        lines.append(f"             ✔ completed: {', '.join(row['courses_completed'])}")
                    if row['courses_in_progress']:
                        lines.append(f"             ↻ in progress: {', '.join(row['courses_in_progress'])}")
                    if row['courses_needed']:
                        lines.append(f"             ✗ still need: {', '.join(row['courses_needed'])}")
                    for w in row['warnings']:
                        lines.append(f"             ⚠️  {w['message']}")

            # Show direct rows (groups without subgroups)
            for row in g['direct_rows']:
                r_icon = STATUS_ICON.get(row['status'], '?')
                dest   = row['destination_requirement']
                ccsf   = row['ccsf_equivalent'] or 'No Articulation'
                lines.append(f"      {r_icon} {dest:35} ← {ccsf}")
                if row['courses_completed']:
                    lines.append(f"           ✔ completed: {', '.join(row['courses_completed'])}")
                if row['courses_in_progress']:
                    lines.append(f"           ↻ in progress: {', '.join(row['courses_in_progress'])}")
                if row['courses_needed']:
                    lines.append(f"           ✗ still need: {', '.join(row['courses_needed'])}")
                for w in row['warnings']:
                    lines.append(f"           ⚠️  {w['message']}")

    if result['warnings']:
        lines.append(f"\n  ⚠️  Warnings ({len(result['warnings'])}):")
        seen = set()
        for w in result['warnings']:
            if w['message'] not in seen:
                lines.append(f"    • {w['message']}")
                seen.add(w['message'])

    lines.append('')
    return '\n'.join(lines)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    json_path = sys.argv[1] if len(sys.argv) > 1 else 'all_agreements_v3.json'

    with open(json_path) as f:
        agreements = json.load(f)

    # ── TEST: Your actual courses so far ─────────────────────────────────────
    # Based on what we know from our sessions — adjust as needed
    completed = [
        "MATH 110A",   # Calculus I
        "MATH 110B",   # Calculus II
        "ENGL C1000",  # Academic Reading and Writing
    ]
    in_progress = [
        "MATH 110C",   # Calculus III (taking now)
    ]

    print(f"Loaded {len(agreements)} agreements")
    print(f"Student completed: {completed}")
    print(f"In progress: {in_progress}")

    # Test 1: Single agreement — UC Berkeley Aerospace
    aero = next(
        a for a in agreements
        if 'Aerospace' in (a['metadata'].get('major') or '')
        and 'Berkeley' in (a['metadata'].get('to_institution') or '')
    )
    result = match_agreement(aero, completed, in_progress)
    print(format_summary(result))

    # Test 2: Compare across all UC Berkeley agreements
    print("\n" + "="*60)
    print("ALL UC BERKELEY AGREEMENTS — ranked by completion")
    print("="*60)
    ucb_results = match_all(agreements, completed, in_progress,
                            school_filter='Berkeley')
    for r in ucb_results:
        ag  = r['agreement']
        ov  = r['overall']
        print(f"  {ov['progress_pct']:5.1f}%  {ag['major']} {ag['degree_type']}")
