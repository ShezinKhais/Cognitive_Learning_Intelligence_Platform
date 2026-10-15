# Session reports and scheduled jobs

Owner: General CS, Phase 7 (#65). Code: `backend/app/api/v1/reports.py`,
`backend/app/services/reports.py`, `backend/app/services/report_pdf.py`,
`backend/app/services/scheduler.py` and `backend/app/services/purge_runner.py`.

A lecturer asks for a report of a session. It is built in the background, and
they follow it until it is ready, then read it as JSON or download it as a PDF.
Neither the building nor the scheduled jobs hold up a live class.

## Routes

| Route | Answers |
|---|---|
| `POST /api/v1/sessions/{session_id}/reports` | 202 at once, with a `ReportJobOut` (`report_id`, `status`). Asking again while yours is still being built returns the same report. |
| `GET /api/v1/reports/{report_id}` | The `ReportJobOut`. Its `report` is set once `status` is `ready`. |
| `GET /api/v1/reports/{report_id}/pdf` | The PDF (`application/pdf`, as an attachment). 409 until the report is ready. |

`status` goes `queued` → `running` → `ready` or `failed`. A failed report has
an `error` (`INTERNAL_ERROR` or `INTERRUPTED`) and a `message` for the
lecturer. Poll every second or two.

**Who may use them.** The lecturer who runs the session, or an admin, with
terms consent. A student gets 403 and someone signed out gets 401. Anyone else
gets 404, worded the same as for a report or session that does not exist, so
an id says nothing about a session the caller may not see. Every response is
`Cache-Control: no-store`.

## What a report holds

`SessionReport` is built from what the session stored, so it can be asked for
during a session or after it:

- the session's course, title, status and times;
- participation: students who joined, questions delivered, answers, missed
  answers and attention prompts;
- topics, hardest first, exactly as `GET /sessions/{id}/topics` serves them;
- alerts, oldest first, exactly as `GET /sessions/{id}/alerts` serves them.

Comprehension and engagement are kept apart, as everywhere else, and no student
is named.

## Not blocking a class

- One report is built at a time. The rest wait their turn.
- Database reads are awaited, and the PDF is rendered in a thread
  (`asyncio.to_thread`), so the event loop the live classes share is never held.
- Reports are kept in memory for an hour after they finish, and at most 200 at
  once. When it is full, the oldest finished report is dropped. When every one
  is still being built, the request gets 503 and should be retried shortly.
- On a restart, a report still being built is marked `INTERRUPTED`.
  Finished reports are lost and are simply asked for again.
- Reports live in one worker's memory, so a second worker would answer
  `GET /reports/{id}` with 404 for a report the first one holds. Production
  already refuses more than one worker (`Classroom.check_wiring`), and its
  message names reports.

The PDF uses the built-in fonts, so nothing is shipped with the app. A
character they cannot draw, such as text in a non-Latin script, shows as a box.
Arabic titles and topics are therefore unreadable in the PDF for now (the JSON
report is unaffected). The report screen (#68) should say so until a Unicode
font, with Arabic shaping and right-to-left layout, is added.
All text is escaped before rendering, so a topic that looks like markup is
printed as written.

## Scheduled jobs

`Scheduler` runs housekeeping jobs on a timer, started and stopped by the app
lifespan (`housekeeping()` in `main.py`):

| Job | Every | Does |
|---|---|---|
| `stranded-material-sweep` | 5 minutes | Ends materials whose processing stopped without recording it. This replaces the hand-written loop it used to be. |
| `expire-reports` | 5 minutes | Drops reports that finished over an hour ago. |
| `retention-purge` | `RETENTION_PURGE_INTERVAL_HOURS` (24 hours by default) | Deletes data past `DATA_RETENTION_DAYS`, see below. |

A job never overlaps itself. One that raises is logged and tried again at its
next turn. Stopping cancels a run in progress. A job must await its I/O and
move CPU-bound work to a thread.

`expire-reports` first runs after 5 minutes. `retention-purge` first runs
after 10 minutes, or after one interval if that is shorter. The scheduler puts
no time limit on a job, so the purge keeps its own, described below.

## The retention purge

The README promises that session data is deleted after `DATA_RETENTION_DAYS`.
The `retention-purge` job keeps that promise on a timer. It runs
`purge_expired_data()` in `purge_runner.py`, which runs the purge runner
(`PurgeRunner`) and holds it to `RETENTION_PURGE_TIMEOUT_MINUTES`. The runner
works through purge tasks. Each task knows one kind of data and deletes a
bounded batch of it, oldest first.

How a run goes:

1. The cutoff is now minus `DATA_RETENTION_DAYS`. The period is read afresh
   each run. A period of zero or less is refused as a misconfiguration and is
   never read as "delete everything"; the setting itself must be at least 1.
2. Tasks run in name order. Each is called with the cutoff and a limit of 500,
   and called again until it returns fewer than 500.
3. Before each batch the runner checks whether a session is running. If one
   is, the whole run stops, and the next carries on because every task deletes
   oldest first. A class that is on when a run starts therefore stops it
   before anything is deleted. After a full batch the runner pauses for 0.05
   seconds, so the database lock and the event loop are never held for long.
4. A task gets at most 500 batches in a run. One that is still not empty is
   marked stopped early, and the other tasks still run.
5. A task that raises is logged, listed as failed and skipped. What it deleted
   before failing still counts.

When the time limit is reached, the run is stopped. It has deleted only whole
batches, the next run continues, and a warning saying so is logged. That is not
counted as a failure.

A run that finishes logs one line that a governance review can find, for
example `retention_purge deleted 12 item(s) older than 2025-12-02 (stored-uploads: 12)`.
A run that gave way to a class ends the line with `stopped early, the next run
continues`.

The one task the application registers is `stored-uploads`
(`StoredUploadPurge`). It deletes lecture files left in `UPLOAD_STORAGE_DIR`
that were last changed before the cutoff, and an upload left under its
temporary name for more than a day. A file is normally deleted as soon as its
material has been processed, so what is left is the file of a material that
failed in a way that might have been temporary.

**What is not purged yet.** No database table is purged. Those tasks are BBIS's
to register. Until they are, `DATA_RETENTION_DAYS` is kept for upload files and
not for the database.

### Registering a purge task (BBIS)

A task has a `name` and an `async purge(cutoff, limit) -> int`. `purge`
deletes at most `limit` items last changed before `cutoff`, oldest first,
commits, and returns how many it deleted. Returning fewer than `limit` says
there is nothing left. Register it before requests arrive, with
`get_purge_runner().register(task)` from `app/services/purge_runner.py`. A name
that is already registered is refused.

The example shows the shape of a task. It is not a decision about which tables
to purge.

```python
from datetime import datetime

from sqlalchemy import delete, select

from app.core.database import get_session_factory
from app.models.attention_signal_summary import AttentionSignalSummary
from app.services.purge_runner import get_purge_runner


class AttentionSummaryPurge:
    name = "attention-summaries"

    async def purge(self, cutoff: datetime, limit: int) -> int:
        async with get_session_factory()() as db:
            ids = (
                await db.scalars(
                    select(AttentionSignalSummary.summary_id)
                    .where(AttentionSignalSummary.window_start < cutoff)
                    .order_by(AttentionSignalSummary.window_start)
                    .limit(limit)
                )
            ).all()
            if not ids:
                return 0
            await db.execute(
                delete(AttentionSignalSummary).where(AttentionSignalSummary.summary_id.in_(ids))
            )
            await db.commit()
            return len(ids)


get_purge_runner().register(AttentionSummaryPurge())
```

Open a session per call and hold nothing between calls. Delete child rows
before the parents they point at, and decide what "last changed" means for each
table.

### Settings

All are in `backend/app/core/config.py` and can be set in `backend/.env`.

| Setting | Default | Meaning |
|---|---|---|
| `DATA_RETENTION_DAYS` | 90 | Data older than this is deleted by the purge. At least 1. |
| `RETENTION_PURGE_INTERVAL_HOURS` | 24.0 | How often the purge runs. |
| `RETENTION_PURGE_TIMEOUT_MINUTES` | 30.0 | How long one run may take. A run cut short carries on at the next. |

Fixed in code: a batch of 500, 500 batches per task in a run, and a pause of
0.05 seconds between batches.

## Not done yet

- **Purging the database.** The runner is scheduled and purges upload files.
  The tasks for the database tables are BBIS's to register (see "The
  retention purge").
- **AI-written summaries in the report.** Luna's `LecturerSummariser` (#138)
  can add a summary paragraph once it merges. Its calls go through the AI
  gateway at background priority.
- **Engagement in the report.** Engagement scores live in memory during the
  session. The per-minute attention summaries (#142) would let a report show
  them afterwards.
- **The report screen and governance panel** are Cyber 2's (#68). These routes
  are what they need.
