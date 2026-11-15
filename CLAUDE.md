# Transfer Tracker API

Backend for the CCSF transfer-tracking mobile app (the "Lichten" project).
A student enters their City College of San Francisco courses; the API matches them
against ASSIST articulation agreements and reports progress toward transferring to
UC Berkeley, UC Davis, UCLA, SFSU, SJSU and USC.

## Session start rule

At the start of a conversation, run `date -u` and compare it with **Last updated**
in the Session log below. If more than 10 hours have passed, open your first reply
with the 2 most recent topics and the 2 next topics from the log before anything else.
At the end of a session, update the log: what was worked on, what's next, and a new
timestamp.

## Session log

**Last updated:** 2026-11-15 22:40 UTC

**Last 2 topics**
1. Added the ASSIST PDF parser to the repo as `parser/parse_assist.py` and fixed its
   `to_institution` regex. Opened PR tevinflowers/Transfer-Tracker-API#1.
2. Fixed the `/match/usc/ge` crash (`UnboundLocalError`), aligned the Python version
   at 3.11, and added `.gitignore`.

**Next 2 topics**
1. Merge PR #1 into `main` so Railway deploys the fixes, then check the live API
   (`/` and `/schools`).
2. Re-run the parser on the agreement PDFs (they're on the user's computer, not in the
   repo) to regenerate `all_agreements_v3.json` with `to_institution` filled in for
   SFSU/SJSU.

## Pipeline

```
ASSIST PDFs → parser/parse_assist.py (pdfplumber) → all_agreements_v3.json
           → matcher.py → api.py (FastAPI) → mobile app
```

## Files

- `api.py`: FastAPI app. Loads both JSON files into memory at startup (paths can be
  overridden with `AGREEMENTS_JSON` / `USC_JSON`). Agreement IDs are list indexes.
  `get_school()` maps agreements to schools, falling back to the PDF filename when
  `to_institution` is null. Endpoints: `/`, `/schools`, `/majors`, `/agreements`,
  `/agreements/{id}`, `POST /match/{id}`, `POST /compare`,
  `POST /compare/school/{school}`, `POST /match/usc/ge`.
- `matcher.py`: pure matching logic, bottom-up:
  course → row → subgroup → group → section → agreement.
  `parse_completion_rule()` reads a group's free-text rule ("Complete 1 sequence…",
  "Select 9.00 units…") into AND/OR plus a minimum count. Rows with no CCSF
  equivalent (`not_articulated`) don't block completion. `python matcher.py` runs a
  sample report.
- `parser/parse_assist.py`: v3 parser.
  - Splits each page into columns at x = 295: left is the destination school, right
    is CCSF. Words within 4pt vertically form one line.
  - A state machine walks the lines: section headers → groups (number + "Complete/Select"
    rule) → subgroups (A–F) → rows. `build_equiv()` turns each column into
    single/AND/OR course logic.
  - v3 added `detect_flags()`, which sets `same_institution_required` and
    `sequence_only` from note text.
  - Run it with: `python parser/parse_assist.py path/*.pdf > all_agreements_v3.json`
- `all_agreements_v3.json`: 112 agreements, 1,459 rows. The older v2 output
  (`all_agreements.json`, rows with an always-empty `notes` field instead of flags)
  was never committed.
- `USC_CCSF_agreement.json`: one agreement with a different layout (GE core-literacy
  categories, a writing requirement, course equivalences). It was not produced by the
  parser.
- Deploy: Railway via `nixpacks.toml` (python311) and `Procfile`
  (`uvicorn api:app --host 0.0.0.0 --port $PORT`).

## Gotchas

- The destination column is called `ucb_requirement` in every agreement, because the
  parser started out on Berkeley PDFs. `matcher.py` relies on that name, so keep it.
- The CSU agreements in the current JSON still have `to_institution: null` until the
  parser is re-run.
- There are no tests yet. To check endpoints, use `fastapi.testclient.TestClient(api.app)`.
- Course codes are normalized to uppercase with single spaces (`normalize_course`).

## Lichten project chats (claude.ai)

Earlier design discussions for this app happened in the user's "Lichten" project chats
on claude.ai. Claude Code sessions can't read those chats. Add key decisions from them
here (app features, target schools, data sources, roadmap) so future sessions have them.

- _(to be filled in)_
