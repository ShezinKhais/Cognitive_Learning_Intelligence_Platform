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

**Only finished sessions.** Retention deletes only sessions whose status is `ended`
or `cancelled`. A `prepared`, `active` or `ending` session is never purged, whatever its
dates say; end it first. The admin run archives to the history database first, like the
scheduled purge, and deletes nothing if that fails.

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
**session** request deletes the session and everything it holds, including the Teams
roster snapshots that name its participants. A session that has not ended or been
cancelled is refused with a 409, because it may still be in a class. A session already
removed by retention counts as done. Executing a **student** request erases that
student's own data and anonymises their account (see 'Erasing a student').

The request row outlives what it deleted: `target_id` is deliberately not a foreign key.

## Erasing a student

Executing an approved student request removes the student's own data: answers and the
labels on them, attention prompts, engagement and attention summaries, attendance and
missed questions, and the student profile with its accessibility and
special-consideration notes. Alerts and recommendations about the student are deleted
too, because their text is generated about the student and can describe them; the
class-level ones, which name nobody, stay. Teams ids and names that point at the
account are cleared.

The account row stays so the audit log and consent records keep a valid reference, but
it identifies nobody: the name becomes "Deleted student", the email a placeholder, and
sign-in is disabled. Audit entries and consent records are never touched.

**If an erasure fails halfway.** The history rows are erased and committed first, then
the main data. If the main step fails, the history rows are already gone but the request
stays `approved`: run `execute` again and it finishes, because erasing is repeatable and
a student who is already gone reports nothing left. The order is deliberate. The other way
round, a failure could leave history rows behind for a request marked executed.

## The history database

Session data is deleted after `DATA_RETENTION_DAYS`. What is kept longer, until the
student graduates, is a **summary per student, course and semester**: sessions attended,
questions attempted and correct, and engagement and gaze as a sum and a count so an
average stays exact. It holds no answers, free text, names or emails.

It lives in its own database, named by `HISTORY_DATABASE_URL`. Empty means history is
off and nothing else changes. Create the empty database, then
`PYTHONPATH=. python scripts/init_history_db.py` creates the tables. Its code is in
`backend/app/history/`; it has its own declarative base, so the main migrations never
see it.

- **Semester label:** calendar half-years, `2026-H1` for January to June and
  `2026-H2` for the rest (`semester_label` in `app/history/repository.py`).
- **Archiving:** each purge batch is added to the summaries and committed in the history
  database *before* anything is deleted. If that fails, the batch is not deleted, the
  failure is logged, and the next run tries the same sessions. A session is added once:
  its id is recorded in `archived_session`, so a retried batch never counts twice.
  Attendance comes from the attendance table, so a student who joined but declined
  monitoring and never answered still gets a row, with zero answers and no engagement.
- **Erasure:** executing a student deletion request erases the student's history rows
  first, then their main data. If the history database is down the request stays
  `approved` and can be executed again. The outcome counts `history_rows`.
- **Reading:** `GET /governance/history/{student_id}` (admin only, audited as
  `HISTORY_VIEWED`), and the student's own export.
- **Never purged automatically.** Rows are removed only by erasing the student.

## A student's own data

Under `/api/v1/me`, students only, accepted terms required:

| Method | Route | Does |
|---|---|---|
| GET | `/me/data` | The student's own data as a JSON download: account, profile, answers with their labels, prompts, engagement, attention summaries, missed responses, deletion requests and history. The accessibility note is not included. |
| POST | `/me/deletion-request` | Ask for their own data to be erased. Body `{"confirm": true, "reason": "..."}`; `confirm` must be `true` so the front end shows the warning first. A different admin must approve it. |
| GET | `/me/deletion-request` | Where the latest request stands: status and dates only |

Each export is audited as `STUDENT_DATA_EXPORTED`, with counts.

## When a failure falls between the two databases

The main and history databases are separate, so no single commit covers both. Each flow is
ordered so that a stop between the two commits leaves work half done, never data lost that
should be kept or kept that should be gone, and the next run finishes it.

| Flow | Order | If it stops between the two commits | Recovery |
|---|---|---|---|
| Retention purge (scheduled and admin) | Archive to history and commit, then delete from main | The session is archived but still in the main database | The next run finds it still expired, skips the archive (its id is in `archived_session`, so nothing counts twice) and deletes it |
| Student erasure | Erase history and commit, then erase main | History rows are gone, the student is still in the main database, and the request is still `approved` | Run `execute` again: erasing is repeatable, and history that is already gone reports nothing left |

What cannot happen: a session deleted without its summary being kept, or a student marked
erased while their history rows remain. If the history database is down, both flows stop
before they touch the main data. These cases are tested against a real second database in
`test_retention.py` and `test_deletion_requests.py`.

## An erasure and a purge at the same time

Erasing a student takes a lock on the student's row before it touches the history
database, and keeps it until the main database commits. A purge takes the same lock
on every student in the sessions it is about to archive. So a purge that meets an
erasure in progress waits for it and then finds nothing of that student left to
archive, and an erasure that starts during a purge waits for the purge. Either order
ends with the student's history erased. `tests/test_erasure_purge_race.py` pauses an
erasure between its two commits, starts a purge, and checks that the purge waits and
that no history is left.

## The audit log

Every deletion step and every purge writes an entry: who did it (empty for a
scheduled purge), what, to which target, and counts. `details`
accepts only numbers, flags and short text, so an answer or a name cannot be written
into it by accident.

The address a request came from is deliberately not recorded. Addresses change with the
network and the place a student joins from, and nothing here uses them, so keeping them
would be personal data held without a purpose.

| Action | Written when |
|---|---|
| `DELETION_REQUESTED` | A request is filed |
| `DELETION_APPROVED` | An admin approves it |
| `DELETION_REJECTED` | An admin rejects it |
| `DELETION_EXECUTED` | A request is carried out, with counts |
| `RETENTION_PURGE` | A purge batch runs, by the scheduler or an admin's run (no user), with counts |
| `RETENTION_RUN` | An admin starts a purge by hand: who asked, and what it deleted |
| `STUDENT_DATA_EXPORTED` | A student downloads their own data, with counts |
| `HISTORY_VIEWED` | An admin reads a student's history, with the row count |

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
| GET | `/history/{student_id}` | A student's kept summaries. Audited |

| Status | When |
|---|---|
| 403 `FORBIDDEN` | Not an admin, or approving your own request |
| 404 `NOT_FOUND` | Unknown request, session or student |
| 409 `CONFLICT` | An open request exists, or the request is in the wrong state |
| 422 `VALIDATION_ERROR` | Bad input, or `confirm` is not `true` |

## The scheduled purge

The purge runner (`app/services/purge_runner.py`) runs once a day from the
scheduler and deletes whatever has outlived `DATA_RETENTION_DAYS`, a batch at a
time, oldest first, giving way to any class that is running. BBIS registers two
tasks with it (`app/services/retention_tasks.py`): `session-data` deletes
sessions past the period, and with them everything they hold; `teams-roster-syncs`
deletes Teams roster syncs on their own received date. Each batch writes one
`RETENTION_PURGE` audit entry with counts, as the system, and no personal data.

`POST /api/v1/governance/retention/run` stays for an admin to run the same rule
by hand, after `GET /retention/preview`. The audit log is never purged.

## Consent records and the account row

Erasing a student keeps their consent records and an anonymised account row, so the audit
log and past sessions still point at something. After the erasure they identify nobody:
the account says "Deleted student", has a placeholder email and no password, and is
inactive; a consent record holds only that account's id, the consent type, yes or no, and
a date. For that reason they are not purged. Our tutor also questioned whether consent
records need keeping long at all, since consent here is a tick on the terms. If a rule is
wanted later, the age of an erasure would have to be recorded first; it is not stored today.

## Teams ids

A Teams user mapping that was never matched to an account holds Teams ids and belongs to
nobody. The `teams-unresolved-mappings` purge task deletes them once they are past
`DATA_RETENTION_DAYS`. A mapping to a live account is kept, and is cleared if that student
is erased. Roster participant rows go with their roster sync.

## Tests

`backend/tests/test_audit_repository.py`, `test_retention.py`,
`test_deletion_requests.py`, `test_governance_routes.py`,
`test_history_repository.py` and `test_my_data_routes.py`. The purge tasks and the
archive are tested at the end of `test_retention.py`. The retention and
deletion tests roll back at the end, so what they delete is never saved.
