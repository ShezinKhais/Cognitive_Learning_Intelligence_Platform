# Session reports and scheduled jobs

Owner: General CS, Phase 7 (#65). Code: `backend/app/api/v1/reports.py`,
`backend/app/services/reports.py`, `backend/app/services/report_pdf.py` and
`backend/app/services/scheduler.py`.

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

The PDF uses the built-in fonts, so nothing is shipped with the app. A
character they cannot draw, such as text in a non-Latin script, shows as a box.
All text is escaped before rendering, so a topic that looks like markup is
printed as written.

## Scheduled jobs

`Scheduler` runs housekeeping jobs on a timer, started and stopped by the app
lifespan (`housekeeping()` in `main.py`):

| Job | Every | Does |
|---|---|---|
| `stranded-material-sweep` | 5 minutes | Ends materials whose processing stopped without recording it. This replaces the hand-written loop it used to be. |
| `expire-reports` | 5 minutes | Drops reports that finished over an hour ago. |

A job never overlaps itself. One that raises is logged and tried again at its
next turn. Stopping cancels a run in progress. A job must await its I/O and
move CPU-bound work to a thread.

## Not done yet

- **The retention purge.** BBIS's `purge_expired()` (`retention.py`) is on
  `Nour-Phase-7` and not yet in a PR. Once it merges, scheduling it is one
  `ScheduledJob` in `housekeeping()`, run daily.
- **AI-written summaries in the report.** Luna's `LecturerSummariser` (#138)
  can add a summary paragraph once it merges. Its calls go through the AI
  gateway at background priority.
- **Engagement in the report.** Engagement scores live in memory during the
  session. The per-minute attention summaries (#142) would let a report show
  them afterwards.
- **The report screen and governance panel** are Cyber 2's (#68). These routes
  are what they need.
