# Lichten

Lichten is a mobile transfer-tracking app for California community college students
moving to 4-year universities. This repo is its backend, the **Transfer Tracker API**:
a student's CCSF (City College of San Francisco) courses are matched against ASSIST
articulation agreements, and the API reports progress toward UC Berkeley, UC Davis,
UCLA, SFSU, SJSU and USC.

Context merged from the claude.ai "Lichten" project, which has 3 chats: "Lichten [Build]",
"Lichten API creation" and "Building CCSF articulation agreement API". Last synced
2026-11-15.

## Session start rule

At the start of a conversation, run `date -u` and compare it with **Last updated**
in the Session log below. If more than 10 hours have passed, open your first reply
with the 2 most recent topics and the 2 next topics from the log before anything else.
At the end of a session, update the log: what was worked on, what's next, and a new
timestamp.

## Session log

**Last updated:** 2026-11-16 01:30 UTC

**Last 2 topics**
1. Built the agreement validator (`parser/validate.py`), with `parser/verified.json`
   and 17 tests in `tests/`. Result on the current data:
   - 2 verified, 43 auto-parsed, 67 needs review.
   - The 2 hand-verified Bioengineering agreements pass.
2. Added the Lichten task list (ASSIST data pipeline, multi-school stress test) and the
   ASSIST API email timeline.

**Next 2 topics**
1. Finish roadmap step 3 in Base44: send Prompts A and B, re-run the checklist, and
   rehearse the demo script.
2. Fix what the validator found, starting with what affects matching:
   - Matcher bug: `pick_n_matched_as_all` (7 groups). `matcher.match_group` treats
     direct rows as all-required even when the rule says "Complete 1 course".
   - Then decide on the SFSU/SJSU duplicates: re-download the SJSU PDFs.

## Working with the owner

- The owner is a beginner ("vibe coder") who learns along the way. Explain terminal
  steps one at a time and define basic concepts. Don't assume familiarity with git,
  pip or deploy tooling.
- They work on a Mac in VS Code and use `python3` / `pip3`.
- **Run commands yourself in the session; don't hand them to the owner.** Claude Code
  sessions run in a cloud copy of this repo and can run the validator, tests and
  parser directly. The owner only needs their Mac for files that live there (the
  ASSIST PDFs). They can upload those to the chat, or connect the Mac folder through
  Remote Control.

## Product

- **Name:** Lichten, from a German/Dutch word meaning "to illuminate." It was formerly
  called ArcPath. The backend is still named "Transfer Tracker."
- **Origin:** the owner couldn't find their major (bioengineering) covered in existing
  transfer tools. First users are CCSF students, with Calc 3 classmates as the first
  beta group.
- **Tagline:** "Many paths. Clear direction. Your future, intelligently mapped."
- **Look:** mobile-first, dark mode, teal accent (#2FA89B). English/Spanish bilingual.
- **Competitor:** PlanMyTransfer.com, which probably got ASSIST data before access was
  restricted.

### Business model
- Freemium: **$4.99/month or $29.99/year**.
- **Free:** tracking, 2 school requirement uploads, California UC/CSU only, Major GPA,
  2 custom deadline tags, 1 year of course planning (an earlier note said 2 semesters),
  notes, reminders.
- **Premium:** unlimited uploads, national and private schools, unlimited tags, longer
  planning, in-course grade monitoring (after beta).
- **Later:** an admin model for entering private-school data, and community uploads so
  students at other community colleges can add their own agreements.

## Architecture

```
ASSIST PDFs → parser/parse_assist.py (pdfplumber) → all_agreements_v3.json
           → matcher.py → api.py (FastAPI, on Railway) → Lichten app (Base44 + Supabase)
```

### Backend (this repo)
- **Repo:** `tevinflowers/Transfer-Tracker-API` (public)
- **Live:** https://transfer-tracker-api-production.up.railway.app (docs at `/docs`)
- **Stack:** FastAPI + uvicorn, with pdfplumber for parsing.
- **Hosting:** Railway. It reads the Python version from `runtime.txt` (`python-3.12`,
  shown as python@3.12.13 in Railway). (`nixpacks.toml` says `python311`; left as-is because that setup deploys fine.) Plus
  `Procfile` (`uvicorn api:app --host 0.0.0.0 --port $PORT`).
  - Write the Python version in `runtime.txt` as `python-3.X`, never `python-3.X.Y`,
    or the build fails.
- **Run locally:** run `pip3 install -r requirements.txt`, then
  `uvicorn api:app --reload`, then open http://localhost:8000/docs

| File | Role |
|---|---|
| `api.py` | FastAPI app. Loads both JSON files into memory at startup (paths can be overridden with `AGREEMENTS_JSON` / `USC_JSON`). Agreement IDs are list indexes. `SCHOOL_ALIASES` maps names like ucb/berkeley to UC Berkeley. `get_school()` falls back to the PDF filename when `to_institution` is null. CORS is open to all origins. |
| `matcher.py` | Matching engine (`match_agreement`, `match_all`), bottom-up: course → row → subgroup → group → section → agreement. `parse_completion_rule()` reads free-text rules ("Complete A or B", "Select 9.00 units…") into `subgroup_logic` (AND/OR) plus `min_count`. Rows with no CCSF equivalent (`not_articulated`) don't block completion. `python3 matcher.py` runs a sample report. |
| `parser/parse_assist.py` | v3 ASSIST PDF parser (see below). |
| `parser/validate.py` | Agreement validator (see "Validator" below). |
| `parser/ligatures.py` | Repairs PDF ligature damage (`Di!erential` → `Differential`). The parser's `norm()` uses it, and `python3 parser/ligatures.py file.json` cleans an existing file. Add words to `KNOWN_WORDS` if new garbled text shows up. |
| `parser/verified.json` | Agreements hand-checked against the ASSIST PDF. Only add an entry after checking it line by line. |
| `tests/` | Unit tests: `python3 -m unittest discover tests`. |
| `all_agreements_v3.json` | 112 agreements (UCB 21, UCLA 20, UCD 28, SFSU 23, SJSU 20) with 1,459 articulation rows. |
| `USC_CCSF_agreement.json` | Built by hand, because USC is private and not on ASSIST. It's a flat GE model (6 core-literacy categories, a writing requirement, course equivalences) that isn't tied to a major. |

**Endpoints**
- `GET /`: health check
- `GET /schools`, `GET /majors?school=X`, `GET /agreements`, `GET /agreements/{id}`
- `POST /match/{id}`: match against one agreement
- `POST /compare`: rank all agreements by completion
- `POST /compare/school/{school}`: rank within one school
- `POST /match/usc/ge`: USC GE checker

**How the parser works**
- pdfplumber word bounding boxes, with a column divider at **x = 295**. The left column
  is the destination school's requirement and the right column is the CCSF equivalent.
  Words within 4pt vertically form one line.
- A state machine walks the lines: section headers → groups (number + "Complete/Select"
  rule) → subgroups (A–F) → rows. `build_equiv()` turns each column into
  single/AND/OR course logic.
- v3 added `detect_flags()`, which reads note text to set `same_institution_required`
  (78 rows) and `sequence_only` (35 rows). v2 had a `notes` field that was always
  empty; v3 rows have no notes field.
- Fixes already made: headers repeated at page breaks don't reset state; mixed-case
  sub-labels ("Required for admission") aren't treated as section headers; group-number
  lines split across y-bands are handled; the BIOLOGICAL SCIENCE header doesn't reset
  mid-group; the `to_institution` regex no longer fails on names with a capital F
  (PR #1).
- Run it with: `python3 parser/parse_assist.py path/*.pdf > all_agreements_v3.json`
- Source PDFs are named `CCSF_to_[SCHOOL]_[Major].pdf`. CCSF's ASSIST institution ID
  is **33**.

**Data schema**
- Agreement → `metadata` (`source_file`, `academic_year`, `date_published`, `major`,
  `degree_type`, `to_institution`) → `requirement_sections[]` → `groups[]`. Each group
  has `group_number` and `completion_rule`, plus `subgroups[]` and/or
  `articulation_rows[]`.
- A row has `ucb_requirement` and `ccsf_equivalent`. Each side is
  `{articulated, logic: single|AND|OR, courses | options}`. A row also has the
  booleans `same_institution_required` and `sequence_only`.
- The destination field is named `ucb_requirement` for **every** school, because the
  parser started out on Berkeley PDFs. `matcher.py` relies on that name, so keep it.
- Course codes are normalized to uppercase with single spaces (`normalize_course`).

**Matching rules (decided)**
- An AND series counts as complete only when every course in it is done. Partial
  progress shows as in-progress with a status per course, not as a flat 0%.
- For OR options, the branch with the most progress is picked automatically.
- `same_institution_required` is shown as a warning in the UI.
- **Counting rules** (fixed 2026-11-16; before this, "Complete 1 course from A"
  required every course in A, which affected 106 groups, including both verified
  Bioengineering agreements):
  - "Complete N course(s) from …" or "Select N from …": N completed **rows** in
    total. A row with a bundled sequence (PHYC 4A + 4AL) counts as one.
  - "Complete N course(s) from A and B": N rows from **each** listed subgroup.
  - "Complete N sequence(s)/series from A, B, or C": N whole **subgroups**.
  - "Select N.00 units from …": add up the destination-side units of completed rows.
  - "N course(s) in M different areas": at least max(N, M) rows. The area variety
    itself isn't checked.
  - Counting never asks for more than CCSF can satisfy (options with no CCSF
    equivalent don't block), which is the same idea as `not_articulated` rows.
  - A group where nothing can be taken at CCSF stays `not_started` (unchanged).
    **Product question for later:** show these as "finish after transfer" instead of
    leaving them unfinished forever.
  - Rules with no count ("Complete the following", "A or B", "A and B") are unchanged.
- Agreements are versioned by `date_published`.

**Known data problems (from an audit on 2026-11-13, unresolved)**
- **The SJSU files are really SFSU data.** They have SFSU codes like MATH 226/227/228,
  while SJSU calculus is MATH 30/31/32. Re-download them, or check whether the parser
  mislabeled them.
- **UC Davis:** the core math, physics, chemistry and biology sections parse with empty
  `subgroups`. Davis Biomedical Engineering is missing.
- **Empty agreements:**
  - Berkeley: Film & Media, History of Art, Legal Studies, Gender & Women's Studies,
    Neuroscience.
  - UCLA: Architectural Studies, Art, Music Composition.
- **Wrong logic:** some "pick one from this list" requirements are parsed as AND
  (Nursing, Psychology).
- **Rows bleeding into each other:**
  - UCLA Neuroscience: MATH 3C → STAT C1000.
  - Berkeley Business: MATH 16B gets English comp.
  - Berkeley Architecture: the physics row swallows social science courses.
- **Missing school names:** `to_institution` is null for SFSU/SJSU in the current JSON.
  The regex is fixed in PR #1, but the parser hasn't been re-run yet.
- **Wrong major names:** "Biology Concentration in Ecology" → "Conservation Biology",
  "Apparel Design" → "Design".
- **Cut titles:** some titles are cut off at line wraps. The garbled ligature text
  (`Di!erential`, `So"ware`) was **fixed 2026-11-16** in both the parser and the data.
- **Clean and verified:** Berkeley and UCLA Bioengineering.
- **Planned:** a validator script and a check of the receiving-school header.
- **Tests:** `python3 -m unittest discover tests` covers the validator and the matcher
  (rule parsing, counting rules, and known results on the verified agreements). There are no API
  tests yet; check endpoints with `fastapi.testclient.TestClient(api.app)`.

### Frontend: Lichten app (Base44)
- **Stack:** Base44 (no-code app builder, which hosts the current app) + Supabase
  (database). The API chat also mentioned React Native or Flutter without deciding.
  **Confirm with the owner which frontend to use before writing UI code.**
- **Pages:** Home/Dashboard (transfer readiness %), Requirements (subpages for
  Cal-GETC/IGETC, UC 7-Course Pattern, CSU Golden Four, Major Prep, University
  Requirements), GPA, Deadlines (California transfer
  dates preloaded), Notes, Course Planning, Profile.
- **Core rule:** the GPA page is the **only** place courses are entered.
  - Each course has: name, semester, units, grade, Cal-GETC/IGETC area (1A, 1B, 1C, 2,
    3A, 3B, 4, 5A, 5B, 5C, 6, None), and toggles for Major Prep and Major GPA.
  - A Base44 bug (fixed 2026-11-16): the Course entity had no Golden 7 / Major GPA
    fields, so those toggles were silently dropped for real users. Demo mode hid it.
  - Saving a course updates every Requirements subpage and the readiness %.
- **GPA page:** courses grouped by semester; a 3-dot menu (Edit/Delete) in place of
  trash icons; a chart with semester and cumulative lines; a toggle between Cumulative
  and Major GPA.
- **Planned Supabase tables:** schools, majors, requirements, articulated CCSF courses.
  Also student course lists and community-uploaded agreements.
- **Base44 prompt order:**
  1. Tagging system + GPA hub (✅ sent and working).
  2. Requirements restructure: rewrite it to read from Supabase.
  3. Course Planning.
  4. Home.
  5. Deadlines, Profile, polish.
- **Demo mode:** sample student Alex Rivera (CCSF Bioengineering, started Fall 2025,
  targeting UC Berkeley + UCLA). Data is kept in memory only and never saved.
- **GE rules built into the app (Base44 prompts 7–10):**
  - **Cal-GETC** replaced IGETC for students who started Fall 2025 or later. It adds a
    required Area 1C (Oral Communication). Students who started earlier can choose
    IGETC or Cal-GETC.
  - **"Golden 7" was a mistake.** It merged two different requirement sets, and the
    app was asked to split them on 2026-11-16. Both are worked out from the course's
    area tag, with no manual toggle:
    - **UC 7-Course Pattern** (UC targets only): 2 English composition (1A + 1B),
      1 math (2), and 4 more from at least 2 of: arts & humanities (3A/3B), social &
      behavioral (4), physical & biological (5A/5B). Each needs a C or better and at
      least 3 units. Plus 60 units and a 2.4 GPA (2.8 for nonresidents).
    - **CSU Golden Four** (CSU targets only): oral communication (1C), written
      communication (1A), critical thinking (1B), math (2), each with a C or better.
      Plus 60 units and a 2.0 GPA. Confirm C vs C- on calstate.edu.
    - Sources: UC "Basic requirements" (admission.universityofcalifornia.edu) and
      CSU "Golden Four" (calstate.edu/apply).
  - **USC** has its own GE (`/match/usc/ge`), not Cal-GETC.
  - **UC Berkeley's College of Engineering** (including Bioengineering) doesn't accept
    IGETC/Cal-GETC. It requires its own H/SS: 6 courses, 2 Reading & Composition +
    4 breadth. The app shows this as an estimate.
  - **Still to check:** whether UCLA Samueli (engineering) has its own GE rules.
- **Per-school majors (done 2026-11-16):**
  - Each target school is a school + major pair.
  - Major GPA is per school: each course has a "Counts toward Major GPA at:" checkbox
    for every target school, and the GPA page has a chip for each school.
  - The major list comes from available agreements. For example, Real Estate isn't
    offered because there's no agreement for it yet.
- **Known app bugs** (fix prompts written 2026-11-16 as Prompts A and B):
  - Demo banner missing.
  - A school + major with no requirement data (USC, Cal State Fullerton) shows as 100%
    complete. Rule: **empty requirements always mean "no data yet", never complete.**
  - Current/future courses should default to In Progress, with optional projected
    grades.
  - Raw translation keys still show on the GPA page ("majorGPA", "MAJORGPA"). The
    label-fix prompt hasn't been sent yet.
- **Course codes must match CCSF's exact codes** (`PHYC 4A`, not `PHYS 4A`), or
  matching against agreements fails. Consider autocomplete from the agreement data.

## Lichten task list (bigger projects, in order)

1. **ASSIST data collection pipeline** (requested 2026-11-16).
   - **Goal:** get every CCSF agreement available, for every UC and CSU and every
     major, so the major list and Major Prep cover real choices.
   - **Rule: don't scrape ASSIST** and don't automate its website. Its undocumented
     endpoints were locked in March 2025 because of scraping. Collect data only in
     these ways:
     - **(a) Official API** — follow up on the early-access request to
       help@assist.org. This is the real long-term answer.
     - **(b) Hand download plus automation:** the owner downloads agreement PDFs by
       hand, and an automated pipeline handles everything after that:
       1. Rename the files to `CCSF_to_[SCHOOL]_[Major].pdf`.
       2. Parse them with `parser/parse_assist.py`.
       3. Validate them with `parser/validate.py` (Data quality plan, layer 2).
       4. Write a report: what's new, what's broken, what needs review.
       5. Publish only the agreements that pass to `all_agreements_v3.json`.
     - **(c) AI agreement upload** (below) for anything ASSIST doesn't cover.
   - **Build the validator first.** More data without checks means more wrong
     readiness %.
   - Do the mid-December re-parse of the 2026–27 agreements through this pipeline.

2. **Multi-school / multi-major stress test** (requested 2026-11-16).
   - Run it once the data covers more than Bioengineering. Make a few test accounts,
     each set up to break something, and check readiness, Major Prep and Major GPA
     for every school. Scenarios:
     - 3+ target schools with a different major at each (UC + CSU + USC mix).
     - The same course counting at one school and not another (Major Prep, Major
       GPA, GE area).
     - A school or major with no data (it must show "no data yet", never complete).
     - A major that exists at one school but not another; a renamed major.
     - Two majors at the same school. UC/CSU applications usually allow one major per
       campus (some allow an alternate), so check the rules and decide whether to
       block it or show it as "alternate".
     - Changing a school's major after courses are tagged: what happens to old Major
       Prep / Major GPA checks?
     - Removing a target school that has tagged courses, then adding it back.
     - OR requirements (the best branch is picked), AND series partly done,
       `same_institution_required` warnings, and `sequence_only` rows.
     - UC 7-Course Pattern vs CSU Golden Four vs USC GE vs Berkeley Engineering H/SS
       at the same time.
     - Course code typos (`PHYS` vs `PHYC`), and In Progress or projected grades
       never counting as complete.
     - Moving between agreement years (2025–26 → 2026–27).
   - Turn each scenario into an automated test in this repo once the matching logic
     moves into the API.

3. **Data quality plan:** see its section below. It's a prerequisite for task 1.

4. **AI agreement upload:** see its section below. Do it after the validator exists.

## AI agreement upload (owner's feature idea, logged 2026-11-16)

**Goal:** a student whose target school isn't covered (a private or out-of-state
school, or any school or major missing from the data) uploads their articulation
agreement and gets the same tracking as built-in schools: Major Prep, Major GPA and
readiness %.

**Likely design (not built yet):**
1. The student uploads a PDF or a screenshot of the agreement.
2. AI (the Claude API) extracts it into the same JSON schema as
   `all_agreements_v3.json`: sections → groups → rows, with AND/OR logic.
3. The extracted agreement runs through the same checks as the validator in the Data
   quality plan.
4. The student reviews and corrects the result on an easy-to-read screen before it's
   used.
5. `matcher.py` then treats it like any other agreement. It's saved per student, with
   optional sharing as a community upload once reviewed.

**Fits the business model:** the free tier gets 2 uploads; Premium gets unlimited
uploads and national or private schools. Related to the "community uploads" and
"admin model" plans.

**When:** after the data quality validator exists (the AI output needs the same
checks), so around roadmap steps 6–10.

## Data quality plan (parked, do before roadmap step 6)

**Why it matters:** wrong agreement data means wrong readiness %. It's fine to wait
for now because the demo only uses Berkeley + UCLA Bioengineering, which are verified
clean.

**Deadline:**
- Do it **before roadmap step 6**, when the major picker shows other majors to users,
  and before any beta tester uses a major besides Bioengineering.
- Best timing: together with the **mid-December re-parse** of the 2026–27 agreements.

**Audit from 2026-11-15** (112 agreements, 1,459 rows):

| Check | Result |
|---|---|
| No `to_institution` | 43 agreements |
| No rows at all | 8 agreements |
| Destination side didn't parse | 42 rows |
| Garbled ligature characters | 90 rows |
| CCSF side mixes 3+ departments (likely row bleed) | 45 rows |

**Plan, in 4 layers:**
1. **Identify agreements from their contents.**
   - Read school, major and degree from the PDF header.
   - Cross-check against the filename and against course-code patterns (for example,
     SFSU calculus is MATH 226 while SJSU's is MATH 30).
   - Flag agreements where these disagree instead of guessing.
2. **Validator script** (`parser/validate.py`), run after every parse.
   - Runs the audit checks above, plus: every requirement has courses, AND/OR rules
     make sense, and no row pulls in unrelated departments.
   - Gives each agreement a status: `verified` / `auto-parsed` / `needs review`.
   - The app shows "may be incomplete, check ASSIST" on anything not verified.
3. **Golden set.**
   - Save hand-checked agreements (start with Berkeley + UCLA Bioengineering) as test
     fixtures.
   - Every parser change must still reproduce them exactly.
   - Add a verified agreement for each major the beta testers have.
4. **`school_rules.json`** for rules ASSIST doesn't cover:
   - Berkeley Engineering H/SS, UCLA engineering GE, the UC 7-Course Pattern, the
     CSU Golden Four,
     minimum GPAs, TAG.
   - Each rule gets a source link and a "last checked" date.
   - Today these rules live only in Base44 prompts.

**Status:**
- **Layer 2: done 2026-11-16** (`parser/validate.py`, details under "Validator").
- **Layer 3: started.** `parser/verified.json` lists the hand-checked agreements, and a
  test fails if any of them gets errors.
- **Layers 1 and 4: not started.** The validator does cross-check filename, PDF header
  and course codes, which covers part of layer 1.

### Validator
- Run it after every parse: `python3 parser/validate.py`.
  - `--details` lists every issue.
  - `--json report.json` saves the full report.
  - `--strict` exits with code 1 if anything needs review, for use in a pipeline.
- **Statuses:**
  - `verified`: in `verified.json` and has no errors.
  - `auto-parsed`: no errors.
  - `needs review`: at least one error.
  - A verified agreement with errors is reported as a **parser regression**.
- **Errors**, where the data is wrong or the matcher would compute the wrong result:
  - `empty_agreement`, `empty_group`, `row_empty` (both sides empty).
  - `school_unknown`, `school_mismatch`.
  - `wrong_school_codes`: calculus codes belong to another campus. See
    `SCHOOL_FINGERPRINTS`, and extend it when adding schools.
  - `duplicate_other_school`: at least 90% the same rows as another school's
    agreement. Only the mislabeled copy is blamed when the course codes show which
    one it is.
  - `suspicious_and_list`: 5+ CCSF courses from 3+ departments, all required. It's
    almost always an OR list read as AND.
- **Warnings:** `count_rule_ambiguous` ("Complete 1 course from the following" over
  several subgroups: the matcher counts in total; check the PDF in case it means per
  subgroup), `dest_unparsed` (the requirement is described in words, like Berkeley
  R&C; matching still works), `no_to_institution`, `garbled_text`, shorter
  suspicious AND lists, `duplicate_same_school`, `rule_letters_mismatch`.
- **Info:** `truncated_title`.
- **First run, 2026-11-16:** 2 verified, 43 auto-parsed, 67 needs review.
  - 46 empty groups, mostly UC Davis.
  - 28 cross-school duplicates (SFSU/SJSU).
  - 12 broken AND lists (Berkeley Architecture requires "all 97" courses).
  - 12 empty rows, 8 empty agreements, 7 pick-N groups, 6 SJSU files with SFSU codes.
  - 171 garbled titles (fixed the same day by `parser/ligatures.py`; now 0).

**After the matcher fix (2026-11-16):** 2 verified, 46 auto-parsed, 64 needs review.
The pick-N problem is fixed in `matcher.py`, so that check was removed.
**Long term:** the official ASSIST API (expected in 2026–27) should mostly remove
parse errors. Layers 3 and 4 stay useful after that.

## ASSIST.org data access
- Third-party API access needs a key. ASSIST restricted the undocumented endpoints in
  March 2025 because of scraping, and public access is expected in the 2026–27
  academic year. **Don't scrape.**
- The beta uses about 100 hand-downloaded PDFs. The architecture is meant to let
  official API data replace them later.
- **API access request timeline:**
  - First email to help@assist.org, around July 2026. ASSIST replied to wait until
    the 2026–27 academic year.
  - Second request sent around mid-November 2026, timed for the new 2026–27
    agreements. Waiting for a reply.
- **While waiting:** don't block on ASSIST.
  - Build the validator (useful for API data and AI uploads too).
  - Keep building the app.
  - If there's still no reply by beta time, download the beta testers'
    majors/schools by hand (about 10–20 PDFs) and run them through the
    parser + validator.
  - Ask the Calc 3 classmates for their majors and target schools to know which
    agreements to get.
- Re-run the parser on the 2026–27 agreements (around mid-December) if the API isn't
  available by then.

## Roadmap (10 steps, from 2026-11-13)
Steps 1–5 are the interview/demo path; steps 6–10 lead to launch.
1. ✅ **No login wall for the demo** (done 2026-11-15):
   - Base44 auth (Google + email).
   - A "Continue as demo" button with a sample CCSF Bioengineering student targeting
     Berkeley + UCLA.
   - Onboarding.
   - Fix the goal shown on Home.
2. ✅ **Clean up Courses** (done 2026-11-15): group by semester, 3-dot menus, rename to Requirements, fix the
   "golden7" label (later replaced by the UC 7-Course Pattern and CSU Golden Four).
3. **Test the tagging flow** end to end and write a 2-minute demo script. *(In
   progress: the script is written, the checklist was run once, and Prompts A/B fix
   what it found.)*
4. **Load real Bioengineering data into Major Prep** (Berkeley + UCLA, from
   `all_agreements_v3.json`), showing CCSF equivalents and AND/OR logic. *(The
   University Requirements tab with school chips is already done, from prompt 7.)*
5. ✅ **GPA upgrade** (done early, 2026-11-16): a cumulative line and a Major GPA
   toggle, both reading the same course list. Major GPA is now per school.
6. **Polish Home, Deadlines and Profile:** per-school readiness *(done early, from
   prompts 4 and 8)*, preloaded UC/CSU dates,
   a major picker with an "Other" upload option, and a language switch.
7. **Course Planning page** (1 year free, more with Premium), with course suggestions.
8. **Spanish toggle, notes, reminders.**
9. **Gate Premium features** and add the $4.99 / $29.99 subscriptions.
10. **Data pipeline and beta:** fix the Known data problems, follow up with ASSIST, then
    run a CCSF student beta and a campus event.

**Next backend steps:**
- Connect the frontend to the API.
- Add Supabase storage for student course lists and community-uploaded agreements.
- Build a separate GPA tracking feature.
