# Merged-main integration audit — 2026-10-17

Historical snapshot. For the current merged-main follow-up and port/deployment
checks, use [the 2026-10-19 integration audit](integration-audit-2026-10-19.md).

Baseline: `b9c21ba` (main after #140, #144, #145 and #150 merged).
This is tested integration evidence, not a guarantee of zero bugs or a
production/real-tenant sign-off. No other open PR was merged for this audit.

## Problems fixed

1. **Stale WebSocket credentials after refresh.** Student live sessions,
   lecturer live sessions and material-progress hooks captured a token at
   mount. After the HTTP refresh mechanism replaced it, reconnects still sent
   the old token, which could cause an unnecessary sign-in. Each handshake now
   reads current storage. A token removed before reconnect is never sent.
   On an authentication close (4001), each hook now attempts refresh once and
   reconnects, signing out if recovery fails or the renewed handshake is refused.
   Recovery is cancelled on unmount. Browser regressions exercise the actual
   hooks over Playwright's mocked WebSocket transport.
2. **Security audit inventory did not cover merged routes.** The full main
   suite failed because refresh and three student-review routes were missing
   from its explicit audience map. These are now classified; review routes
   enter the existing staff-denial, anonymous-denial and terms-consent tests.
   Refresh remains an authenticated bootstrap route (like `/auth/me`), with
   independent bearer/account/expiry tests in `test_token_refresh.py`.
   The obsolete session/summary 501 allowances were removed rather than
   weakening the audit to accept unknown routes.
3. **Outdated student completion message.** Ended sessions now point to the
   existing review link instead of promising a future reporting phase.
   Cancelled sessions do not promise an ended-session review.
4. **Timing-sensitive floating-point assertion.** A full-suite rerun exposed
   four fairness-test failures in the shared baseline helper: duration-weighted
   `0.4` sometimes becomes `0.39999999999999997`. Its three values are now
   checked with the default `pytest.approx` tolerance, matching #162/#163. Production
   scoring, sample count and consent-purge checks are unchanged.

The existing PostgreSQL REST/WebSocket integration test now continues past
session end to student review and the Cyber 1 summary. It verifies the same
saved answer and matching attempted/missed counts, no-store review responses,
and absent historical engagement being represented as unavailable, not zero.

## Verification

An isolated `pgvector/pgvector:pg16` test container was used on
`127.0.0.1:55432` (`clip_test`), not the development database. Migrations through
`c5d8e2f71a40` applied. Use a disposable database for these tests.

- Original merged-main full backend run: **2,683 passed, 1 skipped, 2 failed**.
  Failures: the route inventory fixed above, and the known local WMF conversion
  limitation below. The skip is real OCR without local Tesseract.
- After fixes, focused database-backed security, token-refresh, student-review,
  student-summary and combined integration tests passed in the original audit.
  A subsequent full local run passed **2,688**, skipped **1**, and failed the
  known WMF case plus four instances of the floating-point assertion described
  above; those four are addressed by the follow-up test-only correction.
- Frontend unit/proxy tests: **143 passed**; lint, production build and browser
  test type-check passed.
- Current Docker Chromium browser suite: **46 passed**, including real self-hosted
  camera/VAD startup with synthetic media, CPU throttling, denial/failure,
  consent withdrawal, track cleanup, keyboard/reduced motion, automated
  accessibility checks and socket regressions. Branded Chrome/Edge need a fresh
  CI run for this follow-up. These are not
  physical-device, real-image/voice accuracy or real Teams tests.
- Backend lint/format and generated REST/WebSocket contract checks passed.
- Current focused PostgreSQL security-audit, refresh, live-to-review integration,
  fairness and frontend-contract regression run: **211 passed**, using an isolated database
  `clip_pr161_review_20261018`, migrations through `c5d8e2f71a40`. No development
  data or other workstream schema was used. The test container was stopped afterward.

Full post-fix backend and branded Chrome/Edge results should be read from this
PR's CI run; do not extrapolate them from the focused/local results above.

## Still missing or awaiting release evidence

| Area | Current state and next step |
| --- | --- |
| Staff reporting/governance UI | Aliyeh's #146 remains open, with #151 staff hardening evidence also open. Recheck against Nour's final API before merging. |
| Database governance | Nour's #162 and #163 are open as of the 2026-10-18 review follow-up. Their database retention/deletion/cascade/backup/restore work must be reviewed and integrated separately, not duplicated here. |
| Timetable/roster persistence | `backend/app/api/v1/identity.py` still parses/matches uploads without saving dated sessions or enrolments (`sessions_created=0`). Agree enrolment cardinality and timetable-to-date behaviour before implementing; do not silently move a student between courses. |
| Breakout workflow | The AI2 follow-up adds student room-selection submission over the existing `room.confirm` event, with active/connected/paused checks and explicit error/unacknowledged states. It does not create Teams rooms or automatically assign students. Lecturer `room.status` presentation, recommendation review and final group controls remain separate work; no full group-formation claim is made. |
| Historical engagement | Student review/summary intentionally report unavailable/insufficient data. No verified persisted record with confidence and signal availability is supplied; do not replace it with zero or infer comprehension from it. |
| Real Teams | Tenant permissions/registration, identity mappings, actual notification delivery and meeting lifecycle need a real tenant and HTTPS deployment. Mock bot/connector tests do not establish this. |
| Physical devices and live models | Teams webview, real OS permission behaviour, weaker hardware and screen-reader use need human checks. Synthetic camera/audio are not gaze/VAD accuracy evidence; fake LLMs are not live Ollama grounding/quality evaluation. |
| WMF toolchain | This Mac's LibreOffice produces a blank page for the existing vector-chart fixture; captioning safely rejects it. The test was not disabled or weakened. Verify the supported production converter/toolchain. |
| Dependency audit | `npm audit --json` reports high-severity transitive build-tool advisories involving `nanoid` and `source-map-js`, with propagated Vite/Tailwind findings and no automatic fix reported by that audit response. Review compatible upstream fixes separately; no forced dependency upgrade is included. |
| Durability/deployment | Classification/notification tasks and classroom state are in-process. Do not claim crash-durable jobs or multi-worker live-state support. Re-run the deployment smoke/load/recovery checks on the actual deployment. |

The historical `phase-integration.md` and `integration-candidate.md` record
earlier snapshots; their old “not yet merged” statements are not current PR
status. This audit is the newer checkpoint, not a replacement for the pending
workstreams or a final acceptance decision.

## Agreed follow-up boundaries

The user confirmed **multiple-course enrolment** and **120-day retention** on
2026-10-17, and explicitly asked not to implement Aliyeh's or Nour's work.
These are integration targets, not schema changes delivered by this PR.

- Nour's `Nour-Phase-7` branch already adds governance, student export/erasure,
  cascading deletion and database purge registration, and changes the default
  retention to 120 days. Do not duplicate or cherry-pick that work here. The
  90-day default on current main is not changed by this AI2 follow-up.
- Multi-course persistence needs Nour's agreed profile/enrolment schema and
  updated authorisation queries. Admin timetable imports also need explicit
  dates/timezone; no dated sessions or enrolments are fabricated here.
- Historical engagement needs a verified snapshot contract with confidence,
  availability, timestamps and consent rules, plus Nour's export/erasure/purge
  coverage. No new history table, sensor-data persistence or invented score is
  added here. The student review continues to show unavailable honestly.
- Aliyeh retains lecturer room/group and reporting/governance screens. This
  follow-up changes only the student-side room-selection component and hook,
  its tests, and integration documentation. The existing backend event has no
  success receipt, so the UI reports **sent**, never **confirmed**. Selection
  is not automatically replayed after reconnect; students can send it again.

The remaining three gaps are therefore **not all completed by #161**. The
safe AI2 connection is implemented without taking over the other workstreams.

## Review follow-up — 2026-10-18

- Merged main through `ec46d36` (#146/#151). Kept its default fairness
  tolerance and removed duplicate route-inventory keys from the merge. Refresh
  remains separately token-authenticated in PUBLIC, not a consent-gated route.
- Socket refresh now distinguishes `renewed`, `refused` and `unreachable`.
  Network/5xx failures keep credentials and use the existing bounded reconnect
  backoff; only a definitive refusal signs out. Six browser cases cover an
  interrupted request and HTTP 503 followed by recovery across all three hooks.
- The shared authenticated HTTP path also treats an unavailable refresh as a
  temporary 503 rather than replaying the stale 401 into global sign-out. Two
  unit regressions verify preserved credentials and successful later recovery,
  so concurrent REST checks cannot undo the socket fix during the same outage.
  All 21 socket browser cases were rerun successfully after this final HTTP change.
- #164 is still an unmerged dependency, not part of this branch. When it lands,
  keep its `renewSession`/cookie-auth hooks and port these regression scenarios
  to its in-memory-token harness; do not restore the older bearer-only hooks.
- Removed the harness connection-status key: reconnect no longer remounts the
  room form or erases its typed label. A browser assertion checks preservation.
- Room notices only display room-specific refusals received after a submission;
  unrelated `RATE_LIMITED`/`NOT_IN_SESSION` errors cannot override a sent notice.
  There is still no server success receipt or request id: do not claim confirmed
  membership or exact correlation for generic errors.
- Replaced the misleading random-ID “no stubs” test with checks of a created
  session, its response collection and its ended-session summary. The existing
  live integration test checks a real submitted answer and matching review counts.
- Added a real login → refresh → identity audit test for current main's bearer
  contract. The proposed httpOnly-cookie/in-memory-token rework is not on main:
  its integration must change refresh classification to cookie-authenticated,
  test `X-CLIP-Refresh: 1` and logout, and replace localStorage harness seeding
  with that final contract. No nonexistent logout route is added to this audit.
- The fairness assertion now matches Nour's default `pytest.approx` tolerance.
  Suggested dependency order for overlapping tests: #162, #163, then rebase #161
  and rerun CI. This is a recommendation, not a merge or an agreement on behalf
  of those owners; preserve all route-audit additions when resolving conflicts.
