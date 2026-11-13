# What a backend restart keeps and loses

C.L.I.P runs one API process (`--workers 1`, `WEB_CONCURRENCY=1`). In production it
refuses to start with more. This page says what lives only in that process, what happens to
it when the process restarts, and what the capstone deliberately does not do (#256).

A restart here means the container is stopped with SIGTERM (a deploy, `docker compose
restart`, the host rebooting) and started again. A crash (`kill -9`, out of memory) skips
the shutdown steps in the last column, so anything marked "drained" is lost as well.

## Kept: everything in the database

Accounts, consents, courses, sessions and their status (including paused), materials and
their questions, delivered questions, answers, comprehension results, attention minutes
already committed, alerts, discussion notes, Teams meeting links, and the audit log. Uploaded
files are on the `/data` volume.

## Held in the process

| State | Where | After a restart |
|---|---|---|
| Live sockets | `realtime/hub.py` | Dropped. Clients reconnect and are sent the current state. |
| A running class: question cycle timer, waiting prompts, rooms | `realtime/classroom.py` | Rebuilt from the database the first time the session is touched (a socket joins, the lecturer acts). The delivered count and pause come from the row. The time already waited towards the next checkpoint is not kept: a fresh wait is drawn. |
| An open question | `realtime/classroom.py` | Not reopened. Answers to it are refused ("This question is not open"). Reads treat it as closed at its `closes_at`, with the number of students who could answer unknown; answers stored before the restart are kept. |
| Rolling attention signals | `realtime/classroom.py` | The minute in progress is lost. Minutes already handed to storage are waited for at shutdown. |
| Material processing jobs | `services/jobs.py` | Drained at shutdown; anything still running after that is marked interrupted, and the lecturer sees it failed and can upload again. The stored file is kept. |
| Generated reports | `services/reports.py` | Held for an hour, then dropped. A report still building at shutdown is marked interrupted. Reports are rebuilt from stored data, so asking again gives the same report. |
| Teams notifications waiting to be sent | `services/teams_notifications.py` | Cancelled at shutdown. A pop-up or card not yet sent is not sent or retried. |
| Sign-in rate limits and lockout counters (development) | `auth/address_limiter.py`, `auth/store.py` | Reset. Production lockouts are stored in the database and kept. |
| Development accounts and consents | `auth/store.py` | Development mode only: consents given are forgotten. Production uses the database. |

## What the user sees

- **Student:** the live page shows the connection notice, reconnects, and shows the class as
  it now is. A question that was open at the moment of the restart is gone.
- **Lecturer:** the dashboard reconnects. Pausing, resuming, sending a question and ending
  all work, and rebuild the running class if needed.
- **Material upload:** a job that was cut off shows as failed, with the reason.

## Not done, by decision

Running more than one process would run each class's question cycle twice, so every student
would be asked every question twice. Making that safe needs the per-class state above moved
out of the process: an owner for each running session (a lease in the database or Redis),
timers driven from stored deadlines rather than in-memory tasks, a shared pub/sub for socket
fan-out, and a durable job queue for materials and reports. That is out of scope for the
capstone, which targets one class at a time on one server. Do not raise the worker count
without it.

## Checking it

1. Start a class, connect a student, and send a question.
2. `docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env restart backend`
3. The student's page reconnects within a few seconds. The question that was open is no
   longer answerable, earlier answers are on the results page, and the next checkpoint goes out
   after a fresh wait.

Record the commit, environment and result in the test log (#175) when this is run on the
target deployment.
