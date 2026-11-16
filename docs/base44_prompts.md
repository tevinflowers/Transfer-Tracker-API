# Base44 prompts

Prompts for the Lichten app in Base44, kept here so they don't get lost in chat.
Send them one at a time, in order, and test after each one.

API base URL: `https://transfer-tracker-api-production.up.railway.app`
(interactive docs at `/docs`).

## Still to send (roadmap step 3)

- **Prompt A**: demo banner + "no data is never complete"
- **Prompt B**: In Progress by default + projected grades
- **Label fix**: raw translation keys such as "majorGPA"

These were written in the Claude Code session on 2026-11-16. Send them before the
step 4 prompts below; Prompt C relies on Prompt A's "no data yet" screen.

---

## Prompt C: Major Prep from real ASSIST data (roadmap step 4)

```text
Connect Major Prep to my Transfer Tracker API so it uses real ASSIST articulation data instead of manual tags.

API base URL: https://transfer-tracker-api-production.up.railway.app
All endpoints are public JSON (no key needed, CORS is open).

1. Find the agreement for each target school + major:
   GET /agreements/find?school={school name}&major={major}
   Example: /agreements/find?school=UC Berkeley&major=Bioengineering
   - Response: { count, agreements: [{ id, school, major, degree_type, academic_year, data_status, data_note }], message? }
   - If count is 0: show the existing "We don't have [School] [Major] requirements yet" screen, keep using the user's manual Major Prep tags for that school, and never count it as complete.
   - Otherwise use agreements[0].id.

2. Get the student's progress for that agreement:
   POST /match/{id}
   Body: { "completed_courses": [...], "in_progress_courses": [...] }
   - completed_courses: course codes (like "MATH 110A") of courses with a real grade of C or better, or P. Not projected grades.
   - in_progress_courses: codes of courses marked In Progress.
   - Response:
     - overall: { status, progress_pct, groups_complete, groups_total }
     - agreement: { data_status, data_note, ... }
     - warnings: [ { type, message } ]
     - sections: [ { section_name, status, progress, groups: [ group ] } ]
     - each group: { completion_rule, status, progress, subgroups: [ { label, status, rows } ], direct_rows: [ row ] }
     - each row: { destination_requirement, ccsf_equivalent, status, courses_completed, courses_in_progress, courses_needed, warnings }
     - status is one of: complete, in_progress, not_started, not_articulated

3. On the Major Prep page (with the school chips from before), for the selected school show:
   - The overall Major Prep % (overall.progress_pct) and "X of Y requirement groups complete".
   - Each section as a heading, and each group as a card titled with its completion_rule (for example "Complete 1 course from the following").
   - Inside each card, one line per row: the university requirement on the left (destination_requirement), the CCSF course(s) that satisfy it on the right (ccsf_equivalent; show "No CCSF course. Take after transfer" when it's empty), and a status icon (complete ✓, in progress ↻, not started ○, not articulated –).
   - Under a row that isn't complete, show "Still need: …" from courses_needed.
   - Show row warnings (for example "must be completed at the same college") as a small yellow note.
   - Subgroups (A, B, C) as labeled blocks inside the card.

4. Data quality: if data_status is "needs review", show a yellow banner on that school's Major Prep: data_note plus a link to https://assist.org. If it's "auto-parsed", show a small grey "Automatically read from ASSIST" note. If it's "verified", show a small "Verified" badge.

5. Use the API result everywhere Major Prep shows up for that school: the Major Prep % in its readiness, and University Requirements. When API data exists for a school, the Major Prep tags for that school come from the API (courses listed in courses_completed or courses_in_progress), not manual checkboxes. Keep manual tags only for schools with no data. Keep Major GPA checkboxes as they are, but pre-check them for courses the API says count as Major Prep at that school.

6. Call the API again whenever the user's courses change, and cache the last result per school so the page loads fast. If the API can't be reached, show "Couldn't load requirements. Try again" with a retry button. Never show complete when there's no result.

7. Demo mode: do the same with Alex's courses (these API calls only read data, nothing is saved).
```

**Test afterwards:**
1. In demo mode, open Major Prep and select UC Berkeley. It should show real requirements, a "Verified" badge, and Alex's math, chemistry and English courses marked complete.
2. Select UCLA. The requirements should be different, also verified.
3. Add a course that satisfies a requirement (for example `CS 110C`). Major Prep should update and the readiness % should go up.
4. With a real account, add a school + major with no data (for example USC). It should show "no data yet", never complete.
5. Pick a school + major whose data is "needs review" (for example any SJSU major). The yellow ASSIST banner should appear.

---

## Prompt D: Course code autocomplete and typo check

```text
On the GPA page course form, help students enter the exact CCSF course code so matching works (for example "PHYC 4A", not "PHYS 4A").

API base URL: https://transfer-tracker-api-production.up.railway.app

1. Autocomplete: as the user types in the course name/code field, call
   GET /courses?q={what they typed}&limit=8
   Response: { courses: [ { code, title, units } ] }
   Show the results as a dropdown ("PHYC 4A · Classical Mechanics for Scientists · 3 units"). Picking one fills in the code, title and units (the user can still change units).

2. Typo check on save: before saving, call
   POST /courses/check   with body { "codes": ["THE CODE"] }
   Response: { known: [...], unknown: [ { code, suggestions: [...] } ], note }
   If the code is unknown and has suggestions, show: "We couldn't find PHYS 4A. Did you mean PHYC 4A?" with a button for each suggestion and a "Keep PHYS 4A" button. Picking a suggestion replaces the code. Keeping it saves as typed (some real courses just aren't in any agreement).

3. Do the same check once for existing saved courses: on the GPA page, show a small note on any course whose code is unknown and has suggestions, with a "Fix" button that opens the same choice.

4. If the API can't be reached, skip the check and save normally.
```

**Test afterwards:**
1. Typing "phyc 4" shows PHYC 4A, PHYC 4AL, etc. Picking one fills in the title and units.
2. Saving "PHYS 4A" asks "Did you mean PHYC 4A?". Choosing it fixes the code.
3. Saving "ENGL 1A" suggests "ENGL C1000" (the new code).
4. Your existing "PHYS 4A" course shows a "Fix" note on the GPA page.
