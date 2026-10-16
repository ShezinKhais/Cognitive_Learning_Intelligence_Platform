# Retention, deletion requests and the audit log

Owner: BBIS, Phase 7. Code: `backend/app/services/retention.py`,
`backend/app/services/deletion_requests.py`,
`backend/app/repositories/audit_repository.py` and `backend/app/api/v1/governance.py`.

Everything here is admin only. The rules live in the services, so a scheduled job and
the routes behave the same way.

## The retention purge

A session ages from the day it ended (`ended_at`), or its scheduled end, or its start
when it never formally ended. When it is older than `DATA_RETENTION_DAYS` (default 120,
a semester),
the session row is deleted and the database removes everything it holds:

| Removed with the session | Kept |
|---|---|
| Answers (including free text) and their labels | Lecturer questions: they stay, and only lose their link to the session |
| Engagement records and attention summaries | Uploaded material |
| Attention prompts sent | The audit log, always |
| Alerts, recommendations, delivered questions, attendance | |

Teams roster syncs hold participant names and outlive their session, so they are
purged on their own received date.

The purge reports what it removed as counts. A **dry run** only counts and is the
default in code: `GET /governance/retention/preview`. A real run,
`POST /governance/retention/run`, needs `{"confirm": true}` in the body, deletes for
good, and writes one audit entry with the counts.

## Deletion requests

An admin asks for a session's or a student's data to be erased. A different admin
approves it, and only then can it be executed.

| Status | Meaning | Next |
|---|---|---|
| `requested` | Waiting for another admin | `approved` or `rejected` |
| `approved` | Agreed, nothing deleted yet | `executed` |
| `rejected` | Refused. A new request may be made | none |
| `executed` | Done. `outcome` holds the counts | none |

Rules: the admin who made a request cannot approve it; a target has at most one open
request; a request is decided once; nothing is deleted before approval. Executing a
**session** request deletes the session and everything it holds. A session already
removed by retention counts as done. Executing a **student** request is not available
yet and answers 501.

The request row outlives what it deleted: `target_id` is deliberately not a foreign key.

## The audit log

Every deletion step and every purge writes an entry: who did it (empty for a
scheduled purge), what, to which target, from which address, and counts. `details`
accepts only numbers, flags and short text, so an answer or a name cannot be written
into it by accident.

| Action | Written when |
|---|---|
| `DELETION_REQUESTED` | A request is filed |
| `DELETION_APPROVED` | An admin approves it |
| `DELETION_REJECTED` | An admin rejects it |
| `DELETION_EXECUTED` | A request is carried out, with counts |
| `RETENTION_PURGE` | A real purge runs, with counts |

Nothing deletes audit entries: not retention, and not a deletion request.

## Routes

All under `/api/v1/governance`, admin role and accepted terms required.

| Method | Route | Does |
|---|---|---|
| POST | `/deletion-requests` | File a request: `target_type` (`session` or `student`), `target_id`, optional `reason` |
| GET | `/deletion-requests` | List, optionally `?status=requested` |
| GET | `/deletion-requests/{request_id}` | One request |
| POST | `/deletion-requests/{request_id}/approve` | Approve |
| POST | `/deletion-requests/{request_id}/reject` | Reject |
| POST | `/deletion-requests/{request_id}/execute` | Carry out an approved request |
| GET | `/audit-log` | Newest first. Filters: `action_type`, `user_id`, `target_type`, `target_id`, `since`, `until` |
| GET | `/retention/preview` | What a purge would delete now |
| POST | `/retention/run` | Run the purge. Body `{"confirm": true}` |

| Status | When |
|---|---|
| 403 `FORBIDDEN` | Not an admin, or approving your own request |
| 404 `NOT_FOUND` | Unknown request, session or student |
| 409 `CONFLICT` | An open request exists, or the request is in the wrong state |
| 422 `VALIDATION_ERROR` | Bad input, or `confirm` is not `true` |
| 501 `NOT_IMPLEMENTED` | Executing a student request |

## For the scheduled purge runner

Call `POST /api/v1/governance/retention/run` with `{"confirm": true}` as an admin
once a day. Use `GET /retention/preview` first to see what is due. A scheduled call
has no admin of its own today, so its audit entry records the admin whose token it
used.

## Not done yet

- Erasing a single student waits on the decision whether a student's answers are deleted
  or anonymised.
- Consent records and the `user` row are not touched by any of this yet.
- Unresolved Teams user mappings also hold personal data and are not purged yet.

## Tests

`backend/tests/test_audit_repository.py`, `test_retention.py`,
`test_deletion_requests.py` and `test_governance_routes.py`. The retention and
deletion tests roll back at the end, so what they delete is never saved.
