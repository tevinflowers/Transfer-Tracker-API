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

**Last updated:** 2026-11-15 23:20 UTC

**Last 2 topics**
1. Merged PR tevinflowers/Transfer-Tracker-API#1 into `main`. It contains the USC
   endpoint fix, `parser/parse_assist.py` with the
   `to_institution` fix, `.gitignore`, and this CLAUDE.md.
2. Merged the Lichten project-chat notes into this CLAUDE.md.

**Next 2 topics**
1. Check that Railway deployed the latest `main` commit. If Railway doesn't redeploy
   on its own, use "Redeploy" on the newest deployment. Then check that `/` loads and
   `POST /match/usc/ge` returns 200. The Railway service shows "Unexposed service", so
   check under Settings → Networking that it has a public domain.
2. Re-run the parser on the agreement PDFs (kept on the owner's Mac, not in the repo)
   to fill in `to_institution` for SFSU/SJSU. While doing it, start on the Known data
   problems below, beginning with the SJSU-is-really-SFSU mix-up.

## Working with the owner

- The owner is a beginner ("vibe coder") who learns along the way. Explain terminal
  steps one at a time and define basic concepts. Don't assume familiarity with git,
  pip or deploy tooling.
- They work on a Mac in VS Code and use `python3` / `pip3`.

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
- **Bad characters and cut titles:** ligatures come out garbled (`Di"erential`,
  `Di!erential`, `So"ware`), and some titles are cut off at line wraps.
- **Clean and verified:** Berkeley and UCLA Bioengineering.
- **Planned:** a validator script and a check of the receiving-school header.
- **No tests yet.** Check endpoints with `fastapi.testclient.TestClient(api.app)`.

### Frontend: Lichten app (Base44)
- **Stack:** Base44 (no-code app builder, which hosts the current app) + Supabase
  (database). The API chat also mentioned React Native or Flutter without deciding.
  **Confirm with the owner which frontend to use before writing UI code.**
- **Pages:** Home/Dashboard (transfer readiness %), Requirements (subpages for IGETC,
  Golden 7, Major Prep, University Requirements), GPA, Deadlines (California transfer
  dates preloaded), Notes, Course Planning, Profile.
- **Core rule:** the GPA page is the **only** place courses are entered.
  - Each course has: name, semester, units, grade, IGETC area (1A, 1B, 2, 3A, 3B, 4,
    5A, 5B, 5C, 6, None), and toggles for Golden 7, Major Prep and Major GPA.
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
- **Known app bugs:**
  - Sign In / Create Account goes to a 404 (there's no login page yet).
  - Home shows USC as the goal instead of Berkeley/UCLA.
  - My Courses isn't grouped by semester.
  - The tab label "golden7" is lowercase.
  - "Courses" should be renamed "Requirements".

## ASSIST.org data access
- Third-party API access needs a key. ASSIST restricted the undocumented endpoints in
  March 2025 because of scraping, and public access is expected in the 2026–27
  academic year. **Don't scrape.**
- The beta uses about 100 hand-downloaded PDFs. The architecture is meant to let
  official API data replace them later.
- An email asking for early API access was sent to help@assist.org. Follow up, and
  re-run the parser on the 2026–27 agreements (around mid-December).

## Roadmap (10 steps, from 2026-11-13)
Steps 1–5 are the interview/demo path; steps 6–10 lead to launch.
1. **No login wall for the demo:**
   - Base44 auth (Google + email).
   - A "Continue as demo" button with a sample CCSF Bioengineering student targeting
     Berkeley + UCLA.
   - Onboarding.
   - Fix the goal shown on Home.
2. **Clean up Courses:** group by semester, 3-dot menus, rename to Requirements, fix the
   "golden7" label.
3. **Test the tagging flow** end to end and write a 2-minute demo script.
4. **Load real Bioengineering data into Major Prep** (Berkeley + UCLA, from
   `all_agreements_v3.json`), showing CCSF equivalents and AND/OR logic. Add the
   University Requirements subpage.
5. **GPA upgrade:** a cumulative line and a Major GPA toggle, both reading the same
   course list.
6. **Polish Home, Deadlines and Profile:** per-school readiness, preloaded UC/CSU dates,
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
