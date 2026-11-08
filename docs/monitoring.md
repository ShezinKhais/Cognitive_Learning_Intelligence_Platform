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
- **Unavailable service.** Run
  `python backend/scripts/watch_readiness.py https://your-deployment/api/v1/ready`
  from a host outside the app stack under a process supervisor. Route its output
  to the deployment's existing alert destination. It emits one alert after two
  consecutive failed checks and a recovery message when readiness returns.
  Check the public proxy, API and required database. The probe needs no
  credentials and emits neither the endpoint URL nor the response body.

In a disposable deployment, stop and restart a required service to verify
outage and recovery delivery. Check synthetic server failures for the two-minute
dashboard signal and verify that a synthetic browser report containing sample
private text exposes only its category and area. Record the release, time,
signal and recovery in #175. Operator assignments and real alert delivery are
deployment acceptance steps.
