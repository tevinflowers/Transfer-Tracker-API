"""
Repair PDF ligature damage in parsed text.

ASSIST PDFs print letter pairs like "ff" and "ft" as a single ligature glyph, which
pdfplumber reads back as a stray symbol: "Di!erential", "Di\"erential", "So\"ware",
"A\"er". The same symbol can stand for different letters, so each damaged word is
repaired by trying every ligature and keeping the one that makes a known word.
Words that can't be repaired with confidence are left as they are, and the validator
keeps flagging them as garbled_text.

Used by parse_assist.py (in norm()), and can clean an existing agreements file:

    python3 parser/ligatures.py all_agreements_v3.json
"""

import json
import re
import sys

LIGATURES = ["ff", "ft", "fi", "fl", "ffi", "ffl", "tt"]
DAMAGE_CHARS = '!"#$%'

# Lowercase words that ligature repair may produce. Add words here when the
# validator reports new garbled_text that should be fixed.
KNOWN_WORDS = {
    "differential", "differentials", "different", "difference", "differences",
    "differentiation", "software", "after", "afterwards", "effective", "effects",
    "effect", "efficient", "office", "officer", "official", "offered", "offer",
    "offers", "affairs", "affect", "staff", "traffic", "difficult", "difficulty",
    "sufficient", "scientific", "specific", "certificate", "classification",
    "field", "fields", "fluid", "fluids", "flow", "reflection", "influence",
    "inflation", "shift", "craft", "crafts", "draft", "drafting", "aircraft",
    "left", "soft", "lift", "fifth", "fifty", "artifacts", "identification",
    "first", "film", "films", "final", "finance", "financial", "fine", "fitness",
    "profile", "proficiency", "qualifications", "certification", "attention",
    "pattern", "patterns", "written", "matters", "settings", "battery",
}

DAMAGED_WORD_RE = re.compile(r"[A-Za-z]*[A-Za-z][" + re.escape(DAMAGE_CHARS) + r"][A-Za-z]+")


def _repair_word(word):
    for i, ch in enumerate(word):
        if ch in DAMAGE_CHARS and 0 < i < len(word) - 1:
            for lig in LIGATURES:
                candidate = word[:i] + lig + word[i + 1:]
                if candidate.lower() in KNOWN_WORDS:
                    return candidate
    return word


def fix_ligatures(text):
    """Return text with ligature-damaged words repaired where the fix is certain."""
    if not isinstance(text, str) or not any(c in text for c in DAMAGE_CHARS):
        return text
    return DAMAGED_WORD_RE.sub(lambda m: _repair_word(m.group(0)), text)


def fix_in_data(obj):
    """Apply fix_ligatures to every string in a JSON-like structure. Returns (obj, n_fixed)."""
    count = 0

    def walk(o):
        nonlocal count
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            fixed = fix_ligatures(o)
            if fixed != o:
                count += 1
            return fixed
        return o

    return walk(obj), count


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 parser/ligatures.py agreements.json")
    path = sys.argv[1]
    with open(path) as f:
        data = json.load(f)
    data, n = fix_in_data(data)
    with open(path, "w") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    print(f"Repaired {n} text field(s) in {path}")
