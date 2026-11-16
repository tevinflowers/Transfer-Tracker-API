"""
USC support. USC isn't on ASSIST; it publishes one school-wide agreement with CCSF
(see parser/parse_usc.py → USC_CCSF_agreement.json). This module turns it into:

- a standard agreement (same shape as all_agreements_v3.json) covering USC GE Core
  Literacy, GE Global Perspectives and the writing requirement, so the existing
  matcher and the app's requirement screens work for USC unchanged, and
- extra USC checks: course equivalences, foreign-language level, and whether each
  CCSF course transfers to USC at all.

USC has no major-specific agreements; major prep must be checked on USC department
sites. Course equivalences (e.g. CHEM 101A → CHEM 105A) are the closest thing.
"""

import re

USC_SCHOOL = "USC"
USC_MAJOR = "All majors (general education and writing)"


def _side(entry):
    """'BIO 32 with BIO 32L' → an AND side; 'ART 101' → single."""
    codes = [c.strip() for c in re.split(r"\s+with\s+", entry) if c.strip()]
    return {"articulated": True, "logic": "single" if len(codes) == 1 else "AND",
            "courses": [{"code": c, "title": None, "units": None} for c in codes]}


def _group(number, rule, dest_code, dest_title, entries):
    dest = {"articulated": True, "logic": "single",
            "courses": [{"code": dest_code, "title": dest_title, "units": None}]}
    return {
        "group_number": number,
        "completion_rule": rule,
        "subgroups": [],
        "articulation_rows": [
            {"ucb_requirement": dest, "ccsf_equivalent": _side(e),
             "same_institution_required": False, "sequence_only": False}
            for e in entries
        ],
    }


def build_usc_agreement(usc):
    """USC GE + writing as a standard agreement the matcher can score."""
    ge = usc["ge_requirements"]
    sections, n = [], 0

    core = []
    for key, cat in ge["core_literacy"]["categories"].items():
        n += 1
        letter = key[0]
        title = cat["label"].split(": ", 1)[-1]
        need = cat.get("courses_required", 1)
        rule = f"Complete {need} course{'s' if need > 1 else ''} from the following"
        core.append(_group(n, rule, f"USC GE-{letter}", title, cat["ccsf_courses"]))
    sections.append({"section_name": "USC GE CORE LITERACY", "groups": core})

    global_groups = []
    for key, cat in ge["global_perspectives"]["categories"].items():
        n += 1
        letter = key[0]
        title = cat["label"].split(": ", 1)[-1]
        global_groups.append(_group(n, "Complete 1 course from the following",
                                    f"USC GE-{letter}", title, cat["ccsf_courses"]))
    sections.append({"section_name": "USC GE GLOBAL PERSPECTIVES", "groups": global_groups})

    n += 1
    sections.append({"section_name": "USC LOWER DIVISION WRITING", "groups": [
        _group(n, "Complete 1 course from the following", "WRIT 130", "Writing (= WRIT 150 at USC)",
               ge["writing_requirement"]["ccsf_courses"])]})

    meta = dict(usc["metadata"])
    meta.update({"major": USC_MAJOR, "degree_type": None, "scope": "school-wide"})
    return {"metadata": meta, "requirement_sections": sections}


def _norm(code):
    return re.sub(r"\s+", " ", code.strip().upper())


def _compact(code):
    return re.sub(r"\s+", "", code.upper())


def _all_done(entry, done):
    return all(_norm(c) in done for c in re.split(r"\s+with\s+", entry))


def equivalences(usc, completed, in_progress):
    """Every CCSF → USC course equivalence, with the student's status for each."""
    done, prog = {_norm(c) for c in completed}, {_norm(c) for c in in_progress}
    out = []
    for eq in usc.get("course_equivalences", []):
        need = [_norm(c) for c in eq["ccsf_courses"]]
        have = [c for c in need if c in done]
        going = [c for c in need if c in prog]
        status = ("complete" if len(have) == len(need) else
                  "in_progress" if have or going else "not_started")
        out.append({"ccsf_courses": eq["ccsf_courses"], "usc_courses": eq["usc_courses"],
                    "status": status, "courses_needed": [c for c in need if c not in done]})
    return out


def language_level(usc, completed):
    """Highest USC foreign-language level reached, and by which courses."""
    done = {_norm(c) for c in completed}
    best = {"level": 0, "satisfied_by": None}
    for key, entries in usc["ge_requirements"]["foreign_language"]["levels"].items():
        level = int(key.split("_")[1])
        for entry in entries:
            for alternative in entry.split(" / "):
                if _all_done(alternative, done) and level > best["level"]:
                    best = {"level": level, "satisfied_by": alternative}
    return best


def transfer_status(usc, code):
    """'transfers', 'transfers_with_conditions', 'does_not_transfer' or 'not_listed'."""
    prefix_map = {_compact(p): p for p in list(usc.get("transferable", {})) + list(usc.get("non_transferable", {}))}
    m = re.match(r"^\s*([A-Za-z][A-Za-z &]*?)\s*([A-Za-z]{0,2}\d.*)$", code.strip())
    if not m:
        return {"status": "not_listed", "flags": []}
    prefix = prefix_map.get(_compact(m.group(1)))
    number = _compact(m.group(2))
    if prefix and number in usc.get("transferable", {}).get(prefix, {}):
        flags = usc["transferable"][prefix][number]
        defs = usc.get("transferable_code_definitions", {})
        return {"status": "transfers_with_conditions" if flags else "transfers",
                "flags": [{"code": f, "meaning": defs.get(f, "")} for f in flags]}
    if prefix and number in usc.get("non_transferable", {}).get(prefix, []):
        return {"status": "does_not_transfer", "flags": []}
    return {"status": "not_listed", "flags": []}


def catalog_entries(usc):
    """(code, transfers_to_usc) for every course USC lists in Parts III and IV."""
    for prefix, numbers in usc.get("transferable", {}).items():
        for num in numbers:
            yield f"{prefix} {num}", True
    for prefix, numbers in usc.get("non_transferable", {}).items():
        for num in numbers:
            yield f"{prefix} {num}", False
