# Operational monitoring

General CS owns deployment monitoring. Cyber 1 reviews privacy controls. The
deployment operator should name a primary and backup responder before enabling
an alert destination.

System status shows readiness and the installed API version. Its Recent errors
panel refreshes every 30 seconds and is available to signed-in administrators
who have accepted the terms. The monitoring API reports the installed API
version. Record the deployed image tag or commit alongside incident evidence
when several builds share that version.

Server reports contain severity, code location and exception type when present.
Browser reports contain a fixed failure category and a known area of the app.
They are sent only by signed-in clients, including before terms acceptance so
that failures on the consent screen can be diagnosed. Reports omit raw messages,
request bodies, full URLs and stack traces. A server-generated request ID can
link a report to the corresponding server log. An inbound request ID is omitted
from the dashboard because callers can supply its value.

The dashboard stores up to 200 groups in memory per API process. Groups expire
after 24 hours without a repeat and are cleared when the process restarts.
Collection uses the app's existing backend and has no external provider.
Container logs are a separate diagnostic source. Restrict access to those logs
and use the sanitized dashboard data when sharing incident evidence.

## Alerts and response

- **Elevated server errors.** The dashboard flags at least ten server errors per
  minute in each of the last two completed minutes. Browser reports and
  security warnings are excluded. Check affected dependencies and the grouped
  error locations, compare with recent deployments and rerun the affected
  workflow. This signal is local to each API process.
- **Unavailable service, and error spikes.** Run
  `python backend/scripts/watch_readiness.py https://your-deployment/api/v1/ready`
  from a host outside the app stack under a process supervisor. It alerts once
  after two consecutive failed checks and once when readiness reports an error
  spike (the same two-minute signal as the dashboard), and says when each
  recovers. Readiness carries the spike only as a yes or no, never which errors.
  Messages go to standard output, and to an incoming webhook when
  `CLIP_ALERT_WEBHOOK` (or `--webhook`) is set; Teams and Slack both accept the
  `{"text": ...}` body it sends. Keep the webhook in the environment rather than
  on the command line, where other users of the host can read it. Check the
  public proxy, API and required database. The probe needs no credentials and
  never prints the endpoint URL, the response body or the webhook address.

## Owners and triage

| Role | Who | Does |
|---|---|---|
| Primary responder | Name before enabling alerts | Acknowledges an alert within the working day, starts triage, records the incident in #175. |
| Backup responder | Name before enabling alerts | Takes over when the primary has not acknowledged within two hours. |
| Privacy review | Cyber 1 | Reviews any change to what reports collect. |

Access: the Recent errors panel is admins only. Container logs are for the
responders only; share dashboard data rather than log lines in incident notes.
Retention: dashboard groups last 24 hours without a repeat and end at a restart;
container log retention follows the host's Docker logging settings. Webhook
messages hold only the fixed alert text.

When an alert arrives:

1. **Service down.** Open the readiness URL. If the database is down, check
   `docker compose ps` and the `db` logs; if the API is down, its logs. Restart the
   failed service once. If it fails again, roll back to the last release that worked.
2. **Error spike.** Open System status, Recent errors. Group by location: one
   location means one code path, so compare with the last deploy and roll back if it
   started then. Many locations at once usually means a dependency (database, model
   server) is failing.
3. **After recovery,** record the release, start and end time, cause and fix in #175.

Not alerted on purpose: validation errors, refused sign-ins and permission checks.
They are expected and would bury real failures.

In a disposable deployment, stop and restart a required service to verify
outage and recovery delivery. For a synthetic server failure, press "Send a test
error" on System status (or `POST /api/v1/admin/errors/synthetic?count=10` as an
admin, twice a minute apart, to trip the two-minute spike and the watcher's
alert). It is audited and logs only a fixed message. Check the dashboard signal and verify that a synthetic browser report containing sample
private text exposes only its category and area. Record the release, time,
signal and recovery in #175. Operator assignments and real alert delivery are
deployment acceptance steps.
