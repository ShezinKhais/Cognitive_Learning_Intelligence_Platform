# Phase 7 AI2 — student session review

Students open **Review past sessions** from their workspace or **Review this session** after a live session ends. Direct links use `/student/reviews` and `/student/reviews/:sessionId`. Review navigation works independently of live-session discovery and its feature flag.

## Delivered

- Paginated ended-session history and the signed-in student's own answers, grouped visually by their recorded topic.
- Stored comprehension labels, MCQ correctness, classification confidence, an uncertain-label state, and unavailable classification handling. No new AI scoring, class comparison, or inferred topic aggregate.
- Separate engagement panel. The existing engagement table lacks confidence and signal-availability metadata, so this implementation deliberately reports insufficient verified data rather than inventing a post-session score. Missing signals are not zero and do not imply poor understanding.
- Source links expand stored RAG chunks for the answer's question material. Matches containing the question's stored excerpt are identified; other chunks on its recorded page are explicitly labelled same-page context, not exact citations. Missing/deleted sources have an honest unavailable state. Text is rendered as plain React text, not HTML.
- Loading, retry, empty, expired-session, unauthorized and unavailable-server states. Requests are aborted when navigating away. Review data is not placed in browser persistence; API responses use `Cache-Control: no-store`.

## Additive API adapter and team boundaries

The frozen `GET /sessions/{session_id}/summary/{student_id}` route remains untouched for Cyber 1, and AI 1's pending summary agent is not imported or merged. A small read-only adapter is necessary because existing response/list/summary routes are still stubs and no student-safe chunk route exists:

- `GET /api/v1/student-reviews?limit=20&offset=0`
- `GET /api/v1/student-reviews/{session_id}?limit=20&offset=0`
- `GET /api/v1/student-reviews/{session_id}/responses/{response_id}/sources`

All routes require student role and terms consent. Identity comes from the authenticated principal, never a supplied student id. Database queries restrict session access by course enrollment, require `ended`, and constrain responses to the caller's student id and session. Source queries additionally constrain material and course. Staff and other students cannot use the adapter to read someone else's response. Source responses contain at most five chunks and indicate truncation. The shared OpenAPI snapshot includes these additive endpoints; no migrations or existing contracts change.

`questions_attempted` is the count of stored responses. `questions_missed` counts recorded missed-response events, not wrong answers or all questions in the session. Pagination/filtering affects only the answer list, not these totals; the review-only filter is explicitly page-local.

Cyber 1/BBIS can later provide verified post-session engagement metadata; AI 1/Cyber 1 own validated prose summaries. This PR does not implement staff reporting, PDF export, retention/deletion, new analytics, or a combined engagement/comprehension score.

## Verification

Run frontend `npm test`, `npm run lint`, `npm run build`; backend `pytest -q tests/test_student_review.py tests/test_contract.py`, Ruff and `PYTHONPATH=. python scripts/export_contract.py --check`. The database integration test uses the existing PostgreSQL fixture and skips when PostgreSQL is unavailable; CI should run it with the migrated test database.

Browser acceptance: use an enrolled student with an ended session, review correct/incorrect/unclassified/low-confidence answers, expand missing and available sources, navigate pages and retry a failed fetch. Verify the history and source content at narrow viewport widths and with keyboard controls. Confirm another student's response id and an active session return 404, while staff return 403.
