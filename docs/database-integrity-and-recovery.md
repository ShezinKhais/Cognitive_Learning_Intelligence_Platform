# Database integrity and recovery evidence

Owner: BBIS, Phase 8. Evidence for: database integrity tests, performance queries,
migration rollback, purge simulation, deletion test and backup restoration.

Every run below uses a throwaway database (`clip_evidence`, and a separate
`clip_evidence_history` for the history side) created next to the live one and
never the live data. Each script prints a Markdown section, saved in
[`docs/evidence/`](evidence/). PostgreSQL 16 with pgvector, as in CI.

## Summary

| Check | Script | Result | Evidence |
|---|---|---|---|
| Integrity | `db_evidence.py integrity` | 6 of 6 checks pass | [integrity.md](evidence/integrity.md) |
| Migration rollback | `db_evidence.py rollback` | 46 of 46 steps down and 46 of 46 back up | [rollback.md](evidence/rollback.md) |
| Purge simulation | `db_purge_simulation.py --scale 5` | 9 of 9 checks pass | [purge-simulation.md](evidence/purge-simulation.md) |
| Deletion test | `db_deletion_test.py` | 16 of 16 checks pass | [deletion-test.md](evidence/deletion-test.md) |
| Backup restoration | `db_restore_check.py` | 5 of 5 checks pass | [restore-drill.md](evidence/restore-drill.md) |
| Performance queries | `db_performance.py --scale 10` | slowest query 37 ms, no missing index | [performance.md](evidence/performance.md) |

## Integrity

The schema was built from scratch by applying every migration, then checked:

- There is one migration head, and the database is at it.
- The schema matches the models exactly (no differences from Alembic's comparison).
- Every constraint is validated and every index is valid.
- None of the 21 foreign keys that point at `session` or `student` can block a delete:
  13 point at `session` (11 cascade, 2 set null: `question` and `teams_roster_sync`) and 8
  at `student` (6 cascade, 2 set null: `ai_alert` and `ai_recommendation`).

## Migration rollback

All 46 migrations were downgraded one step at a time from the head to the empty database,
checking after each step that the database stood on the expected revision, then upgraded
one step at a time back to the head. All 92 steps passed. After the full cycle the
integrity checks still pass, so no migration leaves the schema different from the models.

## Purge simulation

A term was seeded on a throwaway database: 30 students, 300 sessions past the retention
period, 200 current sessions and 5 old sessions that are still `active`, `prepared` or
`ending`; 242,137 rows in all. The real purge runner ran against it in batches of 25, with
a "class has started" signal after 3 batches, and then resumed.

- It gave way after 3 batches (75 sessions), resumed, and deleted all 300 expired sessions,
  each once. 142,050 rows were removed in 0.9 s; the slowest batch took 0.10 s.
- Everything under the 200 current sessions was untouched, and none of the 5 live-status
  sessions was purged.
- Questions of the purged sessions stayed, with their session link cleared.
- The audit log adds up to the 300 deleted sessions.
- The history database holds exactly the archived totals: every student's sessions
  attended, answers, correct answers, engagement and gaze counts match what was seeded.
- A second run deleted nothing and counted nothing twice.

## Deletion test

One student was erased end to end through the same services the admin routes call, with a
separate history database.

- The requester cannot approve their own request, and nothing can be executed before
  approval; trying deleted nothing.
- After approval and execution, the student's 204 answers, 204 labels, 102 engagement
  records, 170 attention summaries and 34 attendance rows were gone, and so was their
  history row. The outcome counts matched what was removed.
- Nobody else's data changed by a single row.
- The account is anonymised, not deleted. The request stays, and the audit log holds the
  request, approval and execution, plus the earlier data export, which survived the
  erasure.
- The student's own export now answers "not found", and executing the same request again
  is refused.
- With the history database down, execution stops before it touches anything, and the
  retry afterwards finishes the job.
- A failure *after* the history database has committed (the main step fails after
  erasing, and its work is rolled back) leaves the history rows erased but the student
  and the request intact, with the request still `approved`. Running it again finishes
  the erasure, and the request ends `executed`.

## Backup restoration

A seeded term (22,084 rows across 34 main and 2 history tables) was backed up with
`scripts/database_backup.py`. Every session and student was then deleted from the live
copy, and both databases were restored into new ones.

- The backup files were created with mode 600 (833 KB in all).
- Backup took 0.3 s and restore 0.6 s.
- All 34 main tables and both history tables came back with their exact original row
  counts (21,994 and 90 rows), and the restored database passes all 6 integrity checks.

## Performance queries

On a database of 481,887 rows plus 50,000 audit entries, after `ANALYZE`:

| Query | Time (ms) |
|---|---|
| Purge: next 500 expired sessions | 0.4 |
| Purge: archive totals for 500 sessions | 37.4 |
| Export: a student's answers with labels | 33.2 |
| Export: engagement / attention summaries / prompts | 1.3 / 1.9 / 0.0 |
| Audit log: newest 50, with and without an action filter | 0.0 |
| Erase one student, with about 4,500 cascaded answers | 27.3 |
| Purge one session with its cascades | 2.0 |

The per-student columns are indexed, so exports and erasures use them. The two queries
flagged for reading a big table whole are the planner's choice: they read a large share of
the table, where a scan is cheaper than an index. No index is missing and none was added.

## What this does not show

- **Scale.** The largest run is about 480,000 rows on one laptop. It shows the logic is
  correct and that a term of this size purges in about a second. It is not a production
  load test.
- **Synthetic data.** The seeded term is regular by design, so its totals can be checked
  exactly. Real classes are messier.
- **A restore undoes later work.** Erasures made after a backup are restored with it (see
  [backup-restore.md](backup-restore.md)).
- **The live database was not tested.** Nothing here ran against `clip`, by design.

## How to reproduce

From `backend/`, with the PostgreSQL client tools on the PATH and a database user that may
create databases:

    PYTHONPATH=. python scripts/db_evidence.py prepare
    PYTHONPATH=. python scripts/db_evidence.py integrity
    PYTHONPATH=. python scripts/db_evidence.py rollback
    PYTHONPATH=. python scripts/db_purge_simulation.py --scale 5
    PYTHONPATH=. python scripts/db_deletion_test.py
    PYTHONPATH=. python scripts/db_restore_check.py
    PYTHONPATH=. python scripts/db_performance.py --scale 10

Each prints its Markdown to the screen (the progress goes to the error output) and exits 1
if a check failed.
