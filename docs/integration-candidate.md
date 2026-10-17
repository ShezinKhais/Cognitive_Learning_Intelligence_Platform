# Combined integration candidate

This branch is a **candidate for review, not a bug-free or production-ready
sign-off**. It combines the existing work from #147 (`28f180b`), #154
(`6ec052d`), #155 (`a5c5d3c`) and connection groundwork #157 (`702e96f`).
Original commits and authors are preserved. Main and the original PR branches
are untouched. It carries work from Phases 3 to 8: the session routes and free-text marking
(Phases 3 and 5), breakout rooms and refocus prompts (Phase 6), the purge
runner (Phase 7), and the load test, the polish and Teams notifications
(Phase 8).
The Phase 7 student-review PR #140 and browser evidence PR #150 are not merged
into this candidate. Coordinate the overlapping original PRs before merging
this umbrella PR; it is not an additional independent implementation.

## Connected here

- Session list, session details and response list use the database, with role,
  lecturer ownership and student enrolment checks; students see only their own
  responses. These Phase 3 routes no longer return 501.
- Stored free-text responses reach the background classifier through the AI
  gateway. Classification does not delay the student's answer receipt.
- The classroom has breakout-room status, refocus prompts and attention
  aggregation wired alongside response recording and classification.
- Authenticated Teams conversation references and optional notifications are
  wired into question delivery. Notifications remain off unless configured.
- REST and WebSocket requests share a configurable backend origin. Frontend
  unit/proxy tests run in CI. Demo Docker build/runtime settings now also pass
  through optional local attention and backend-only Teams configuration.

## Regressions fixed on this branch

1. **Audit atomicity:** the audit decorator registers a SQLAlchemy before-commit
   hook while an endpoint runs. A service committing inside the endpoint must
   include its audit before announcing success. Tests prove audit failure rolls
   back the state change and prevents the announcement; ordinary endpoint
   failure leaves no audit, and the listener is removed afterward.
2. **Breakout activity:** a student's answer increments room task activity only
   after recording succeeds. Three failed saves followed by one successful
   retry count as one interaction, not four. The no-recorder test seam still
   counts an accepted response.
3. **Late comprehension alerts:** both a committed question-close and a committed
   classification recheck the question. A delivery-row lock serializes the
   existing-alert check and insert, so concurrent callbacks persist one alert.
   The reader uses the same database transaction (no nested pool checkout).
   Open questions do not alert early; labels completing after session end can
   still create a persisted alert. Explanation failures retain a safe fallback.

## Evidence and reproducible checks

An isolated local PostgreSQL/pgvector container was used, published only on
`127.0.0.1:55432`; the development database was not used. All migrations through
`b74d1c93ea20` applied successfully.

The initial complete backend run passed 2,061 tests with no database skips and
failed one existing environment-dependent test:
`test_a_vector_chart_is_converted_trimmed_and_described`. This Mac's LibreOffice
produces a blank WMF page; the existing application safely rejects it instead
of inventing a caption. The test has **not** been disabled or weakened. Two
additional regression cases were subsequently added; final results are in the
PR and CI, not inferred from that earlier count.

Database regression coverage includes classification-before-close,
classification-after-close, concurrent first refreshes, fallback explanations,
student/lecturer response visibility, consent/audit atomicity and Teams
notification stores. A new combined REST/WebSocket test covers session
discovery → permission check → student join → room confirmation → delivery →
answer receipt → scored feedback → response retrieval → session end.

Frontend: 94 tests passed; lint and production build passed. Backend lint,
formatting and generated REST/WebSocket contract checks passed. The demo Compose
configuration validates without starting or replacing a deployment.

Run against a disposable PostgreSQL database with extensions `vector`,
`uuid-ossp`, and `pg_trgm`:

```sh
# backend/, with DATABASE_URL pointing to the disposable database
alembic upgrade head
pytest -q
ruff check .
ruff format --check .
python scripts/export_contract.py --check

# frontend/
npm ci
npm test
npm run lint
npm run build
```

## Unresolved release gates — do not call all six phases complete

1. **Imports do not persist enrolments or dated sessions.** Timetable/roster
   uploads parse, match and validate, but explicitly save nothing and return
   `sessions_created=0`. The student schema permits one course per user;
   multi-course enrolment needs an agreed schema/API change, not a silent
   reassignment. Existing database-backed session workflows can be tested with
   seeded records, but that is not a successful admin import workflow.
2. **Breakout UI and group formation are incomplete.** The backend accepts
   `room.confirm` and emits `room.status`, but this frontend has no connected
   confirmation/status/group-formation UI. Room recommendations and lecturer
   control require the corresponding workstreams' implementation/contract.
3. **Real Teams validation remains.** Tenant registration, approved permissions,
   identity mappings, HTTPS deployment, actual card delivery and meeting
   lifecycle need a real tenant. Mocked connector tests are not tenant sign-off.
4. **Real browser/device and model evaluation remain.** Verify camera/mic denial,
   opt-in/disable, no raw-media transmission, keyboard/reduced-motion behaviour,
   Chrome/Edge/Teams webview, weak devices and real Ollama grounding/accuracy.
   Do not count synthetic model responses as an accuracy evaluation.
5. **Known local WMF conversion failure and dependency advisories.** Resolve or
   explicitly accept supported-format/toolchain limitations before release.

The in-process classification/notification jobs are best-effort, not durable
work queues across a process crash. This candidate does not claim exactly-once
notification delivery or automatic recovery of an interrupted classification.
