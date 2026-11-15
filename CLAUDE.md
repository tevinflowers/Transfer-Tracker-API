# CLAUDE.md — Lichten

Context carried over from the claude.ai "Lichten" project (3 chats: "Lichten [Build]", "Lichten API creation", "Building CCSF articulation agreement API"). Last synced: 2026-11-15.

## What Lichten is
A mobile transfer-tracking app for California community college students moving to 4-year universities. It started from the owner's own trouble finding his major (bioengineering) covered in existing transfer tools. The first users are CCSF (City College of San Francisco) students, with Calc 3 classmates as the first beta group.

- **Name:** Lichten, from a German/Dutch word meaning "to illuminate." It was formerly called ArcPath, and the backend is still named "Transfer Tracker."
- **Tagline:** "Many paths. Clear direction. Your future, intelligently mapped."
- **Look:** mobile-first, dark mode, teal accent (#2FA89B used in docs). English/Spanish bilingual.
- **Competitor to know about:** PlanMyTransfer.com, which probably got ASSIST data before access was restricted.

## Owner / working style
- The owner describes himself as a beginner ("vibe coder") who learns as he goes. Explain terminal steps one at a time and define basic concepts. Don't assume he knows git, pip or deploy tooling.
- He works on a Mac in VS Code and uses `python3` / `pip3`.

## Architecture (two halves)

### 1. Backend: Transfer Tracker API (this is the code)
- **Repo:** `tevinflowers/transfer-tracker-api` (public on GitHub)
- **Live:** https://transfer-tracker-api-production.up.railway.app (docs at `/docs`)
- **Hosting:** Railway, using nixpacks. The Python version must be written `python-3.12`, not `python-3.12.0`, or the build fails.
- **Stack:** FastAPI + uvicorn, pdfplumber for parsing.

**Files**
| File | Role |
|---|---|
| `parse_assist_v3.py` *(not in this repo yet; lives on the owner's Mac)* | Parses ASSIST.org articulation PDFs into JSON. Uses pdfplumber word bounding boxes with a column divider at **x=295**: left column = destination-school requirement, right column = CCSF equivalent. |
| `all_agreements_v3.json` | 112 parsed agreements (UCB 21, UCLA 20, UCD 28, SFSU 23, SJSU 20), 1,459 articulation rows. |
| `USC_CCSF_agreement.json` | USC built by hand (USC is private and not on ASSIST). It is a flat GE model, not tied to a major. |
| `matcher.py` | Matching engine (`match_agreement`, `match_all`). Takes completed and in-progress CCSF course codes and returns per-section, per-group and per-row status, progress %, and warnings. |
| `api.py` | FastAPI app. Data paths can be overridden with the `AGREEMENTS_JSON` / `USC_JSON` env vars. Includes `SCHOOL_ALIASES` normalization (ucb/berkeley → UC Berkeley, etc.) and CORS. |

**Endpoints**
- `GET /`: health check
- `GET /schools`, `GET /majors?school=X`, `GET /agreements`, `GET /agreements/{id}`
- `POST /match/{id}`: match against one agreement
- `POST /compare`: rank all agreements by completion
- `POST /compare/school/{school}`: rank within one school
- `POST /match/usc/ge`: USC GE checker

**Run locally:** `pip3 install fastapi uvicorn` then `uvicorn api:app --reload`, and open http://localhost:8000/docs

**Data schema notes**
- Agreement → `metadata` (incl. `source_file`, `date_published`) → `requirement_sections[]` → `groups[]` → `subgroups[]` / `articulation_rows[]`.
- Each row has `ucb_requirement` (`courses` or `options`), `ccsf_equivalent` (`articulated`, `courses`), `notes[]`, plus the booleans **`same_institution_required`** (78 rows) and **`sequence_only`** (35 rows).
- Completion-rule text like "Complete A or B" vs "Complete A, B, and C" is parsed into `subgroup_logic` (AND/OR) and `min_count`.
- PDF source files are named `CCSF_to_[SCHOOL]_[Major].pdf`. CCSF's ASSIST institution ID is **33**.

**Matching rules (decided)**
- An AND series counts as complete only when every course in it is done. Partial progress shows as in-progress with a status per course, not as a flat 0%.
- For OR options, the branch with the most progress is picked automatically.
- `same_institution_required` is shown as a warning in the UI.
- Agreements are versioned by `date_published`.

**Parser fixes already made:** headers that repeat at page breaks no longer reset state; mixed-case sub-labels ("Required for admission") are no longer treated as section headers; group-number lines split across y-bands are handled; the BIOLOGICAL SCIENCE subject header no longer resets mid-group.

**Known data problems (unresolved, from an audit on 2026-11-13)**
- **The SJSU files are really SFSU data** (SFSU codes like MATH 226/227/228; SJSU calculus is MATH 30/31/32). Re-download them, or check whether the parser mislabeled them.
- **UC Davis** core math, physics, chemistry and biology sections parse with empty `subgroups`. Davis Biomedical Engineering is missing.
- **Empty agreements:** Berkeley Film & Media, History of Art, Legal Studies, Gender & Women's Studies, Neuroscience; UCLA Architectural Studies, Art, Music Composition.
- Some "pick one from this list" requirements are parsed as AND (Nursing, Psychology).
- Rows bleed into each other (UCLA Neuroscience MATH 3C → STAT C1000; Berkeley Business MATH 16B gets English comp; Berkeley Architecture physics row swallows social science courses).
- Every school's field is named `ucb_requirement`, and `to_institution` is null for SFSU/SJSU.
- Some major names are wrong ("Biology Concentration in Ecology" → "Conservation Biology", "Apparel Design" → "Design").
- Ligature garbage: `Di"erential`, `Di!erential`, `So"ware`. Some titles are cut off at line wraps.
- **Clean and verified:** Berkeley and UCLA Bioengineering.
- Planned fixes: a validator script and a check of the receiving-school header.

### 2. Frontend: Lichten app (built in Base44)
- **Stack chosen:** Base44 (no-code app builder) + Supabase (database). Base44 hosts the current app. *Note: the API chat also mentioned React Native or Flutter without deciding. Confirm with the owner which frontend to use before building UI code.*
- **Pages:** Home/Dashboard (transfer readiness %), Requirements (subpages for IGETC, Golden 7, Major Prep, University Requirements), GPA, Deadlines (California transfer dates preloaded), Notes, Course Planning, Profile.
- **Core rule:** the GPA page is the **only** place courses are entered. Each course has name, semester, units, grade, IGETC area (1A, 1B, 2, 3A, 3B, 4, 5A, 5B, 5C, 6, None), and toggles for Golden 7, Major Prep and Major GPA. Saving a course updates every Requirements subpage and the readiness %.
- **GPA page:** courses grouped by semester; a 3-dot menu (Edit/Delete) in place of trash icons; a chart with semester and cumulative lines; a toggle between Cumulative and Major GPA.
- **Planned Supabase tables:** schools, majors, requirements, articulated CCSF courses. Also student course lists and community-uploaded agreements.

**Base44 prompt order:** (1) tagging system + GPA hub ✅ sent and working → (2) Requirements restructure (rewrite to read from Supabase) → (3) Course Planning → (4) Home → (5) Deadlines, Profile, polish.

**Known app bugs:** Sign In / Create Account goes to a 404 (no login page yet); Home shows USC as the goal instead of Berkeley/UCLA; My Courses isn't grouped by semester; the tab label "golden7" is lowercase; "Courses" should be renamed "Requirements".

## Business model
- Freemium: **$4.99/month or $29.99/year**.
- **Free tier:** tracking, 2 school requirement uploads, California UC/CSU only, Major GPA, 2 custom deadline tags, 1 year of course planning (an earlier note said 2 semesters), notes, reminders.
- **Premium:** unlimited uploads, national and private schools, unlimited tags, longer planning, in-course grade monitoring (after beta).
- **Planned later:** an admin model for entering private-school data, and community uploads so students at other community colleges can add their own agreements.

## ASSIST.org data access
- Third-party API access needs a key. ASSIST restricted the undocumented endpoints in March 2025 because of scraping, and public access is expected in the 2026–27 academic year. Don't scrape.
- The beta uses about 100 hand-downloaded PDFs. The architecture is meant to let official API data replace them later.
- An email asking for early API access was sent to help@assist.org. Follow up, and re-run the parser on the 2026–27 agreements (around mid-December).

## Roadmap (10 steps, from 2026-11-13)
Steps 1–5 are the interview/demo path; 6–10 lead to launch.
1. Demo opens without a login wall: Base44 auth (Google + email), a "Continue as demo" button with a sample CCSF Bioengineering student targeting Berkeley + UCLA, onboarding, and fix the Home goal.
2. Clean up Courses: group by semester, 3-dot menus, rename to Requirements, fix the "golden7" label.
3. Test the tagging flow end to end and write a 2-minute demo script.
4. Load real Bioengineering data into Major Prep (Berkeley + UCLA from `all_agreements_v3.json`), showing CCSF equivalents and AND/OR logic, and add the University Requirements subpage.
5. GPA upgrade: cumulative line and Major GPA toggle, both reading the same course list.
6. Polish Home, Deadlines and Profile (per-school readiness, preloaded UC/CSU dates, major picker with "Other" upload, language switch).
7. Course Planning page (1 year free, more with Premium), with course suggestions.
8. Spanish toggle, notes, reminders.
9. Gate Premium features and add $4.99 / $29.99 subscriptions.
10. Data pipeline fixes (see Known data problems), ASSIST follow-up, then a CCSF student beta and a campus event.

**Next technical steps for the backend:** connect the frontend to the API, add Supabase storage for student course lists and community-uploaded agreements, and build a separate GPA tracking feature.
