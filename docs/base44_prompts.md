# Base44 prompts

Prompts for the Lichten app in Base44, kept here so they don't get lost in chat.
Send them one at a time, in order, and test after each one.

API base URL: `https://transfer-tracker-api-production.up.railway.app`
(interactive docs at `/docs`).

## Order to send

1. ✅ Prompt A, ✅ Prompt B (sent 2026-11-16), then the label fix.
2. ✅ Prompt C, ✅ Prompt C2, ✅ Prompt D (sent 2026-11-16). **Next: Prompt C3**
   (fixes from testing C2 and D), then the label fix if it's still needed.

---

## Prompt C3: Suggestions on every Major Prep card, and free-text courses

Testing C2 and D showed two gaps:
- **San Jose State "Engineering" showed "no data yet" with no way forward.** SJSU has
  Civil, Computer and Mechanical Engineering, but there's no plain "Engineering"
  agreement. The University Requirements card didn't offer the API's suggestions, and
  the ASSIST banner only appears once a real agreement is chosen.
- **The autocomplete for "RE" listed unrelated courses.** That's fixed in the API: it
  now matches code prefixes, plus title words for 3+ letters. CCSF Real Estate
  courses aren't in any agreement, so the API returns an empty list with a message.

```text
Two fixes, using my Transfer Tracker API (https://transfer-tracker-api-production.up.railway.app):

1. Everywhere Major Prep appears for a school (the Major Prep page AND the Major Prep card on University Requirements), when GET /agreements/find returns count 0:
   - Show the "We don't have [School] [Major] requirements yet" text.
   - If "suggestions" isn't empty, show "Did you mean…?" with one button per suggested major (for example San Jose State: Civil Engineering, Computer Engineering, Mechanical Engineering). Tapping one sets that school's major to it in the profile and reloads.
   - Also show the yellow data-quality banner (data_status "needs review" with data_note and an https://assist.org link) on the University Requirements card when the school's agreement needs review, not only on the Major Prep page.

2. Course autocomplete on the course form:
   - Only call GET /courses?q=… once at least 2 characters are typed (wait about 300 ms after typing stops), and show exactly the courses the API returns. Don't add, re-sort or filter the list in the app.
   - If the API returns no courses, show one line under the field: "Not in our course list. You can still add it." Then let the student type the code, title and units themselves and save normally. Don't run the "Did you mean" typo check for these courses unless the API's /courses/check returns suggestions.
```

**Test afterwards:**
1. San Jose State with major "Engineering" shows "Did you mean…?" buttons on both
   the Major Prep page and the University Requirements card. Tapping **Mechanical
   Engineering** shows its requirements with the yellow ASSIST banner. (All SJSU data
   needs review: those files are copies of SFSU's.)
2. Typing "RE" shows "Not in our course list. You can still add it." Adding
   "RE 184 Real Estate Practice, 3 units" still saves.
3. Typing "phyc 4" lists PHYC 4A, 4AL, 4B…, and "calc" lists the calculus courses.

---

## Prompt C2: Fixes after testing Prompt C

Testing C showed four problems:
- **UCLA and SJSU found nothing.** The API didn't understand names like "UC Los
  Angeles (UCLA)". That's fixed in the API.
- **"Engineering" showed Aerospace Engineering's requirements.** The API used to
  swap in a partial match. Now it returns suggestions instead.
- **A false 100%.** That was a matcher/data problem, now handled cautiously in the
  API.
- **No banner or message for SJSU and Sonoma.**

```text
Update Major Prep to match changes in my Transfer Tracker API (base URL https://transfer-tracker-api-production.up.railway.app):

1. GET /agreements/find now returns:
   { school, school_has_data, major, count, agreements: [...], suggestions: [...], message? }
   - "agreements" holds ONLY exact matches for that school + major. Use agreements[0] when count > 0.
   - "suggestions" holds similar majors at that school (for example "Engineering" → Aerospace Engineering, Bioengineering, Civil Engineering, Mechanical Engineering). NEVER load a suggestion automatically.
   - When count is 0, show the "We don't have [School] [Major] requirements yet" screen (also for schools with no data at all, like Sonoma State), and below it, if there are suggestions, show "Did you mean…?" with one button per suggestion (major name). Tapping one changes that target school's major in the profile to the suggestion, then reloads Major Prep.

2. Major picker: when the student adds or edits a target school, load the majors we have data for from GET /majors?school={school name} (each item has "major" and "degree_type"). Show those first, plus an "Other (no requirement data yet)" option with a text box.

3. Remove any cached Major Prep results and fetch again for every target school (results from before this change may be wrong).

4. Use the API's numbers for status: the big % and "X of Y requirement groups complete" come from overall in POST /match/{id}, and each section/group status comes from the response. Don't compute your own "complete".

5. Show the data-quality banner from agreements[0].data_status:
   - "needs review": yellow banner with data_note and a link to https://assist.org (for example, every San Jose State major currently shows this).
   - "auto-parsed": small grey note "Automatically read from ASSIST".
   - "verified": small "Verified" badge.
   Replace the footer "Lists are representative — verify course-by-course articulation for this campus on ASSIST.org." with: "Requirements come from ASSIST.org agreements for [academic_year]. Always confirm with a counselor."
```

**Test afterwards:**
1. Set UC Berkeley's major to **Bioengineering**. Major Prep should show the real
   agreement, with a Verified badge. Its admission requirements are CHEM 1A, MATH
   51–54, PHYSICS 7A/7B and R&C (there should be no ASTRON or MCELLBI rows).
2. UCLA Bioengineering, Biology and Economics should all show requirements.
3. Set a school's major to "Engineering". You should see "no data yet" plus "Did you
   mean…?" buttons.
4. San Jose State (any major) should show the yellow ASSIST banner.
5. Sonoma State should show "no data yet".
6. 100% should only appear when nothing is left under "Still need".

---

## Prompt A: Demo banner and missing-data bug

```text
Fix two bugs:

1. The demo banner is missing. In demo mode, show a small teal banner at the top of every page: "You're viewing a demo. Create an account to save your progress." Make "Create an account" link to sign-up, and add an "Exit demo" link that goes back to the Welcome page. Keep it visible while scrolling, but small enough not to cover content on a phone.

2. Schools with no requirement data show as complete. For example, tagging one course as Major Prep for USC marked all USC requirements complete, but there is no USC major requirement data at all.
   - If a school + major has no Major Prep requirement data, never show it as complete or count it as 100%. Instead show: "We don't have [School] [Major] requirements yet. Your tagged courses are saved and will count once requirements are added." Show the courses the user tagged for that school as a simple list.
   - Leave Major Prep out of that school's readiness % until data exists, and show a small note under the readiness % saying "Major Prep not included (no data yet)".
   - Apply the same rule to every requirement type and every school (for example, Cal State Fullerton). Empty requirements always mean "no data yet", never "complete".
```

**Test afterwards:**
1. Demo mode shows the banner on every page, and "Exit demo" works.
2. USC and Fullerton show "We don't have … requirements yet" instead of complete, and their readiness % shows the "no data yet" note.

---

## Prompt B: In Progress by default, plus projected grades

```text
Improve how current and future courses work on the GPA page:

1. Default to In Progress. When adding a course in the current semester or a future one, set the grade to "In Progress" by default. Work out the current semester from today's date: Spring = January–May, Summer = June–July, Fall = August–December. Past semesters still need a real grade.

2. Projected grades. For In Progress courses, add an optional "Projected grade" field to the course form. It's just a guess the student can change any time, and it never counts as a real grade.
   - Show it on the course row as "IP · projected A-".
   - Add an "Include projected grades" switch on the GPA page, off by default. When it's on:
     - Show a "Projected GPA" number next to the real GPA (for both Cumulative and per-school Major GPA).
     - Draw the projected part of the GPA Trend chart as a dashed line.
   - Requirements and readiness % always use real grades only. Projected grades never mark anything complete.

3. When a semester ends (based on today's date), show a reminder on the GPA page for any courses still In Progress from past semesters: "Add your final grades for [Semester]", with a button to edit them. If a course has a projected grade, pre-fill it as a suggestion.

4. Demo: give Alex's Fall 2026 courses projected grades (MATH 110C: B+, PHYC 4A: A-, PHYC 4AL: A, BIO 100A: B) so the switch can be shown in the demo. Keep them In Progress.
```

**Test afterwards:**
1. A new Fall 2026 course defaults to In Progress, while a new Spring 2026 course asks for a grade.
2. Turning on "Include projected grades" shows a Projected GPA and a dashed line on the chart. Readiness % doesn't change.

---

## Label fix: raw translation keys

```text
Some labels show raw translation keys instead of words. Add proper English and Spanish text for every key, for example:
- majorGPA → "Major GPA" (Spanish: "Promedio de la especialidad")
- MAJORGPA heading → "MAJOR GPA"
- noMajorGPAData → "No courses tagged for Major GPA yet. Edit a course and check the schools it counts toward." (with a button to open the course list)
- semesterGPALabel → "Semester GPA" (Spanish: "Promedio del semestre")
- cumulativeGPALabel → "Cumulative GPA" (Spanish: "Promedio acumulado")
Check the whole app for any other raw keys showing (camelCase words with no spaces, like "majorGPA") and fix those too. Don't change anything else.
```

**Test afterwards:** no camelCase words like "majorGPA" or "semesterGPALabel" anywhere in the app.

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
