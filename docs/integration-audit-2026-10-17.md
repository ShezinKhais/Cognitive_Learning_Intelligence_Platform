# Merged-main integration audit — 2026-10-17

Baseline: `b9c21ba` (main after #140, #144, #145 and #150 merged).
This is tested integration evidence, not a guarantee of zero bugs or a
production/real-tenant sign-off. No other open PR was merged for this audit.

## Problems fixed

1. **Stale WebSocket credentials after refresh.** Student live sessions,
   lecturer live sessions and material-progress hooks captured a token at
   mount. After the HTTP refresh mechanism replaced it, reconnects still sent
   the old token, which could cause an unnecessary sign-in. Each handshake now
   reads current storage. A token removed before reconnect is never sent.
   Six browser regression cases exercise the actual hooks over Playwright's
   mocked WebSocket transport (refresh and removal for each hook).
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
  student-summary and combined integration tests: **223 passed**.
- Frontend unit/proxy tests: **105 passed**; lint, production build and browser
  test type-check passed.
- Docker Chromium browser suite: **29 passed**, including real self-hosted
  camera/VAD startup with synthetic media, CPU throttling, denial/failure,
  consent withdrawal, track cleanup, keyboard/reduced motion, automated
  accessibility checks and the six new socket regressions. These are not
  physical-device, real-image/voice accuracy or real Teams tests.
- Backend lint/format and generated REST/WebSocket contract checks passed.

Full post-fix backend and branded Chrome/Edge results should be read from this
PR's CI run; do not extrapolate them from the focused/local results above.

## Still missing or awaiting release evidence

| Area | Current state and next step |
| --- | --- |
| Staff reporting/governance UI | Aliyeh's #146 remains open, with #151 staff hardening evidence also open. Recheck against Nour's final API before merging. |
| Database governance | Nour's remaining Phase 7/8 work has no open PR at this snapshot. Database retention/deletion/cascade/backup/restore evidence and governance endpoints must arrive and be integrated. The purge runner currently registers upload-file cleanup, not a complete database-retention implementation. |
| Timetable/roster persistence | `backend/app/api/v1/identity.py` still parses/matches uploads without saving dated sessions or enrolments (`sessions_created=0`). Agree enrolment cardinality and timetable-to-date behaviour before implementing; do not silently move a student between courses. |
| Breakout workflow | Backend `room.confirm`/`room.status` exist, but the frontend has no handlers or connected group-confirmation/status/formation interface. Group recommendation and lecturer final control still need a UI/API contract and an end-to-end test. This is separate from the merged attention-indicator display. |
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
