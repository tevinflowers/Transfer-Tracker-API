"""
CCSF course catalog parser → data/ccsf_catalog.json

Reads one or more years of the CCSF college catalog (PDF pieces, in page order) and
builds a list of every CCSF course: code, title, units, credit type, whether it's
UC transferable, and old codes it replaced ("Formerly BIO 80C").

Course descriptions look like:

    Accounting (ACCT)                              ← department header
    ACCT 1 -Financial Accounting (5.0)             ← course header (units may be "1.0-3.0")
    Credit (Degree Applicable)
    ...
    Catalog Notes: Formerly ...
    UC Transferable

Degree requirement tables ("R E 184 Real Estate Practice 3.0") are also read, as a
fallback for any course that has no description entry.

Usage (pieces of one catalog year, in order):
    python3 parser/parse_catalog.py --year 2026-27 part1.pdf part2.pdf ...
Merges into data/ccsf_catalog.json (other years already in the file are kept).
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ligatures import fix_ligatures  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "ccsf_catalog.json"

PREFIX = r"[A-Z][A-Z&]*(?: [A-Z&]{1,4})*?"       # "MATH", "R E", "PE A", "M B"
NUMBER = r"[A-Z]?\d{1,4}[A-Z]{0,3}"               # "110A", "C1000", "A60"
HEADER_RE = re.compile(rf"^(?P<prefix>{PREFIX}) (?P<num>{NUMBER}) ?- ?(?P<title>.+?)"
                       rf" \((?P<units>\d+(?:\.\d+)?(?: ?- ?\d+(?:\.\d+)?)?)\)$")
HEADER_START_RE = re.compile(rf"^(?:{PREFIX}) {NUMBER} ?-\S")
TABLE_RE = re.compile(rf"^(?P<prefix>{PREFIX}) (?P<num>{NUMBER}) (?P<title>[A-Z][^\n]*?) "
                      rf"(?P<units>\d{{1,2}}\.\d)(?: ?- ?\d{{1,2}}\.\d)?$")
DEPT_RE = re.compile(r"^(?P<name>[A-Z][A-Za-z,&'’/ .-]+) \((?P<prefix>[A-Z][A-Z& ]{0,8})\)$")
# Only one-to-one renames ("Formerly ENGL 1B"). Combined ones ("Formerly SPAN 2A + 2B")
# aren't renames of a single course, so they're skipped.
FORMERLY_RE = re.compile(rf"Formerly ({PREFIX} {NUMBER})\b(?!\s*(?:\+|&|/|,|and\b|or\b))")
SKIP_RE = re.compile(r"^(=====PAGE \d+=====|CCSF Catalog - \d{4}/\d{2} Page \d+)$")


def norm(s):
    return fix_ligatures(re.sub(r"\s+", " ", s or "").strip())


def pdf_lines(paths):
    import pdfplumber
    for path in paths:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for line in (page.extract_text() or "").splitlines():
                    yield line


def parse_lines(lines):
    """Returns (courses, departments, table_courses)."""
    lines = [norm(l) for l in lines]
    lines = [l for l in lines if l and not SKIP_RE.match(l)]
    courses, departments, table = {}, {}, {}
    current = None
    i = 0
    while i < len(lines):
        line = lines[i]
        # Course headers can wrap: "BIO 21M -Coastal Ecosystem Field" / "Studies (2.0)"
        candidate = line
        if HEADER_START_RE.match(line) and not HEADER_RE.match(line) and i + 1 < len(lines):
            joined = f"{line} {lines[i + 1]}"
            if HEADER_RE.match(joined):
                candidate, i = joined, i + 1
        m = HEADER_RE.match(candidate)
        if m:
            code = f"{m.group('prefix')} {m.group('num')}"
            units = re.split(r" ?- ?", m.group("units"))
            current = {
                "code": code,
                "title": m.group("title").strip(),
                "units": float(units[0]),
                "units_max": float(units[-1]),
                "credit_type": None,
                "uc_transferable": False,
                "formerly": [],
            }
            courses[code] = current
            i += 1
            continue
        d = DEPT_RE.match(line)
        if d:
            name = d.group("name").strip()
            prev = lines[i - 1] if i else ""
            # Long names wrap: "African American" / "Studies (AFAM)"
            if (prev and len(prev) < 40 and re.fullmatch(r"[A-Z][A-Za-z,&'’/ .-]+", prev)
                    and not prev.endswith(".") and not HEADER_START_RE.match(prev)):
                name = f"{prev} {name}"
            departments[d.group("prefix").strip()] = name
            current = None
            i += 1
            continue
        if current is not None:
            if current["credit_type"] is None and (line.startswith("Credit") or line.startswith("Noncredit")):
                current["credit_type"] = line
            elif line == "UC Transferable":
                current["uc_transferable"] = True
            for old in FORMERLY_RE.findall(line):
                if old != current["code"] and old not in current["formerly"]:
                    current["formerly"].append(old)
        else:
            t = TABLE_RE.match(line)
            if t:
                code = f"{t.group('prefix')} {t.group('num')}"
                table.setdefault(code, {"code": code, "title": t.group("title").strip(),
                                        "units": float(t.group("units"))})
        i += 1
    return courses, departments, table


def build_year(lines):
    courses, departments, table = parse_lines(lines)
    only_in_tables = {}
    for code, row in table.items():
        prefix = code.rsplit(" ", 1)[0]
        if code not in courses and any(c.rsplit(" ", 1)[0] == prefix for c in courses):
            only_in_tables[code] = {**row, "units_max": row["units"], "credit_type": None,
                                    "uc_transferable": None, "formerly": [],
                                    "source": "program requirement table"}
    return courses, departments, only_in_tables


def merge(existing, year, courses, departments, extra):
    """Add one catalog year to the combined catalog (newest year's details win)."""
    out = existing or {"catalog_years": [], "departments": {}, "courses": {}}
    years = set(out["catalog_years"]) | {year}
    out["catalog_years"] = sorted(years)
    newest = out["catalog_years"][-1] == year
    for p, name in departments.items():
        if newest or p not in out["departments"]:
            out["departments"][p] = name
    for code, c in {**extra, **courses}.items():
        cur = out["courses"].get(code)
        if cur is None:
            cur = {**c, "catalog_years": [year]}
        else:
            if newest:
                keep_years = cur["catalog_years"]
                cur = {**c, "catalog_years": keep_years}
            cur["catalog_years"] = sorted(set(cur["catalog_years"]) | {year})
            cur["formerly"] = sorted(set(cur.get("formerly", [])) | set(c.get("formerly", [])))
        out["courses"][code] = cur
    out["courses"] = dict(sorted(out["courses"].items()))
    out["departments"] = dict(sorted(out["departments"].items()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse CCSF catalog PDFs into data/ccsf_catalog.json")
    ap.add_argument("--year", required=True, help="catalog year, e.g. 2026-27")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("pdfs", nargs="+", help="catalog PDF pieces in page order")
    args = ap.parse_args(argv)

    courses, departments, extra = build_year(pdf_lines(args.pdfs))
    out_path = Path(args.out)
    existing = json.loads(out_path.read_text()) if out_path.exists() else None
    merged = merge(existing, args.year, courses, departments, extra)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    print(f"{args.year}: {len(courses)} course descriptions, {len(extra)} more from requirement "
          f"tables, {len(departments)} departments. Catalog now has {len(merged['courses'])} "
          f"courses across {merged['catalog_years']}.", file=sys.stderr)


if __name__ == "__main__":
    main()
