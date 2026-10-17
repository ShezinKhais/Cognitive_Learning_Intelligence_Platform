# Cyber 1, Phase 7: responsible-AI and privacy validation of reports

Issue #70. Deliverable: *reports meet responsible-AI and privacy requirements*.
Branch `hunain-phase-7`, built on `main`. Location named by the issue:
`GET /sessions/{session_id}/summary/{student_id}` (`sessions.py`), which was a
`501 not_implemented("Cyber 1", "Phase 7")` stub.

## 1. What it does

* **The route is implemented** from stored values only (`services/student_report.py`):
  questions attempted (distinct), questions missed (`missed_response` through
  `delivered_question`, this session only), a comprehension label per topic, engagement,
  and action items. Nothing in it is written by a model, so no sentence can invent a fact.
* **Validation** (`services/report_validation.py`, pure functions) is applied to every
  summary before it leaves, and is reusable for any text about a student (AI 1's written
  summaries can call `text_problems`). It refuses: labels about the person ("lazy"),
  comparison with others or "the class", raw camera/voice readings, accommodations or health
  matters, merged engagement+comprehension figures, inferring understanding from engagement
  or the reverse, instructions aimed at a model, markup/links, mixed-alphabet words, and
  another student's name. Topic names (which a lecture may legitimately make about a camera
  or a voice) are held only to the attack rules.
* **Fail-safe**: a summary that fails is rebuilt without action items, engagement and any
  bad topic; if it still fails the request errors rather than serving it.
* **Separation**: engagement and comprehension are different fields; there is no combined
  field (tested), and engagement can never be the reason for an action item (kinds are
  restricted to `revisit_topic` and `review_missed`).
* **Action items** (additive `action_items` field): fixed templates filled with a counted
  number or a screened topic name. Struggling topics first, then partial, then missed
  questions, capped at 5.
* **Same labels everywhere**: a student's topic label is their own average on the same thirds as the
  class topic difficulty, counting every classified answer exactly as `topic_difficulty` and AI 1's
  student summary do, so one student never reads two different labels. How sure the classifier was
  decides only what is *suggested*: a topic is turned into an action item only when at least one of
  its answers was classified with confidence >= 0.6.
* **Post-session only (REQ-1.10)**: nothing is served until the session has ended. A prepared,
  active, ending or cancelled session answers with the same 404 as a session that does not exist.
* **Access and privacy**: a student reads only their own summary; the lecturer who runs the
  session or an admin read any student on its course; every other case (other lecturer,
  other student, other course, unknown ids) is the same 404. Engagement is included only
  if the student currently consents to engagement monitoring, and only from the running
  class's own score; otherwise it reads `insufficient_data` with no signals.
* **No per-signal engagement detail**: the engagement block uses the same staff view as
  `/engagement` (`engagement_view.py`, identical to #143's): `signals_available` is
  `['participation']` or empty and `confidence` is 0 or 1 (participation evidence or not), the same for every student,
  so a summary cannot reveal that an accommodation rule applied.
* **Audit**: staff reading a student's summary leave a `security_event=STUDENT_SUMMARY_VIEWED`
  log line (viewer, student, session) and an `audit_log` row (viewer, action, IP). Reading
  your own leaves none. A failed audit write never blocks the read.

## 2. Contract change (additive, flagged)

`StudentSessionSummary` gains `action_items: list[ActionItem]` (default `[]`), and a new
`ActionItem` schema. Nothing is removed or renamed. The route's path and the frozen
fields are unchanged.

## 3. Verification

ruff, format, contract check, single alembic head, full pytest on Postgres. Mutation pass:
44 deliberate breaks of the new rules, access checks, counts and audit; 43 caught, one
equivalent (`attempted` counts distinct questions, but the table's unique constraint already
allows one response per student and question). The survivors on the first run each got a
test (attack topic in an action item, session mismatch, topic names in the summary, missed
count scoped to the session, partial-topic suggestion).

## 4. Residual risks

| # | Risk |
|---|---|
| R19 | Phrase lists are heuristics; they catch the cases listed and will miss novel wording. They are the second line behind templates that contain no model text |
| R20 | The `audit_log` table has no column for the target student, so that lives only in the log line until Nour's governance columns (Nour-Phase-7) land; a follow-up should pass the target through `audit_repository` once merged |
| R21 | Engagement is available only while this process runs the class (scores are not stored), so a post-class summary reads `insufficient_data` |
| R22 | AI 1's written summaries (Luna-Phase-7) are not yet wired to `text_problems`; the function is ready for them |
