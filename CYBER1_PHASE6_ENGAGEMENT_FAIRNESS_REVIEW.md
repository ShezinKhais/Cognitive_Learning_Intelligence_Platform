# Cyber 1, Phase 6: engagement that stays usable and fair when signals are missing

Issue #64. Deliverable: *engagement remains usable and fair when signals are missing*.
Branch `hunain-phase-6`, built on `main`.

## 1. Defects found on main (reproduced before changing anything)

| # | Defect | Effect |
|---|---|---|
| D1 | A camera reading alone produced a status | A student with no participation yet, whose camera said "looking away", was `at_risk`/`disengaged` |
| D2 | Every signal weighed the same | A student who answered everything but looked at notes was averaged down by two camera readings (1.0, 0.0, 0.0 -> 0.33) and nudged |
| D3 | Fixed ideal for gaze, face and speed | Someone who reads from notes, has a badly placed camera or types slowly was always penalised |
| D4 | Nothing for accommodations | `Student.accessibility_need` existed and was never consulted |
| D5 | Socket had no frame-size limit; unknown fields in `signal.attention` were silently ignored | Nothing stopped a client sending media-sized frames or extra data inside a valid event |

## 2. What changed

* `services/engagement.py` (v2). Weighted renormalisation (participation 1.0, camera 0.5);
  a status needs at least one participation signal; a student whose participation reads
  engaged cannot be lowered by the camera; prompts need a participation signal;
  every unscored signal has an internal reason (`EngagementComputation.unavailable`).
* `services/engagement_baseline.py`. Per-student, per-session baselines: gaze against the
  student's own median (floor 0.25, needs 3 samples), face presence set aside when the
  camera finds the face in under half of readings, answer speed against the student's own
  median (only slowing down costs). Bounded to 60 samples, dropped with the session,
  never stored, never compared between students.
* `realtime/accommodations.py`. Looked up once at join (`ws.py`). Only the boolean is kept;
  the text of `accessibility_need` is never read into scoring, logged, or sent. For an
  accommodated student: answer speed, gaze and face presence are not scored, a prompt left
  to expire is not held against them, they are never `disengaged` and never auto-prompted.
  A record that cannot be read counts as accommodated (the safe mistake is to flag less).
* Camera consent withdrawal now also purges the camera-derived baseline (`purge_visual`).
* Privacy verification: `AttentionSignalPayload` is closed (`extra="forbid"`), frames over
  64 KiB (text or binary) close the socket with 1009, and `tests/test_privacy_verification.py`
  guards the schema allowlist, absence of binary columns and raw reading columns, no
  readings in logs, the single place `accessibility_need` is read, and the frontend
  (no media-recording/serialising APIs; sockets only send `JSON.stringify`).

## 3. Judgment calls

1. Camera corroborates, never accuses (D1/D2). Weight 0.5, floor on engaged participation.
2. Baselines are session-scoped and in memory: a student's normal is theirs for one class.
3. Accommodation handling is deliberately conservative: fewer flags, no automatic nudges.
4. Unreachable accommodation data is treated as "accommodated".
5. Confidence is weight contributed over weight that could apply, so an accommodated student
   is not shown as low-confidence for signals that never applied to them.

## 4. Contract changes (stricter/clarified, flagged)

`events.schema.json`: `signal.attention` now has `additionalProperties: false`. The
frontend's `signals.ts` (ai2-phase-6) sends exactly the four allowed fields. No REST change.
On `GET /sessions/{id}/engagement`, `signals_available` now holds `['participation']` or nothing, and
`confidence` is 0 or 1 (participation evidence present or not), for every student. Field names and
types are unchanged; the descriptions say so. The Cyber 2 panel shows unknown names as "Other
available signal", so it should map `participation` to a label.

## 5. Verification

ruff check / format, `export_contract.py --check`, alembic single head (no migration here),
full pytest against Postgres. Mutation pass: 46 deliberate breaks of the new guards, all
caught (7 first survived and each got a test: prompt gating, gaze clamp, speeding up,
face-rate threshold, baseline wiring, error-text logging, join-time lookup).

## 6. Residual risks

| # | Risk |
|---|---|
| R14 | **Resolved after review (Aliyeh, Luna).** `signals_available` and `confidence` per student would have let a lecturer tell who has an accommodation, because answer speed, gaze and face presence are never scored for them. Staff now see one view computed the same way for every student, from whether any participation signal backed the score (`engagement_view.py`): `signals_available` is `['participation']` or empty, `confidence` is 0 or 1, camera detail is never named. The scorer keeps the detail internally. What remains: `score` and `status` are still shown, and an accommodated student cannot be `disengaged` or prompted, so a lecturer who watches one student's status over a whole class could still form a suspicion; that is the price of not penalising them |
| R15 | Accommodation is read at join; a change mid-class applies at the next join |
| R16 | The baseline learns one reading per closed question (the latest signal), not every signal |
| R17 | Engagement scores are still in memory only (no `engagement_record` writer); a restart loses them |
| R18 | The frontend scan is a tripwire, not proof: it catches the obvious media APIs, not every way to send bytes |
