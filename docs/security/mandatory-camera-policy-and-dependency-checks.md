# Mandatory camera-policy and dependency fixes

Addresses #237 and #236. This change does not activate adaptive gaze,
anti-spoofing, per-class switches, pacing controls or other optional additions.

## Camera-off accommodations

`GET /api/v1/me/consideration/policy` returns only `camera_allowed`, with
`Cache-Control: no-store`. It is restricted to the signed-in student with terms
consent; monitoring consent is not needed to learn that capture is prohibited.
It includes every approved request still applicable on the server's UTC date,
including its last day. A newer pending request or longer non-camera approval
cannot mask an active camera-off approval. Expired, withdrawn, rejected and
pending requests do not grant a restriction. Request notes, decision notes and
diagnoses are not returned or inferred from legacy free text. Other need types
retain their existing server scoring accommodation behavior.

The live optional-indicator controls verify consent and camera policy before
both automatic and manual device starts. Camera-off overrides saved camera
consent. The controls refresh policy and consent every five seconds during an
enabled live session, even with devices off, so expiry and remote decisions are
noticed. Each verification has a five-second timeout. A failed policy check
stops/prevents camera capture; a failed monitoring-consent check stops both
devices. A changed policy is therefore applied on the next completed check,
not an instantaneous push notification.

Stop, disconnect, hidden-page and unmount events invalidate pending starts.
A late permission result releases its media tracks through the existing sensor
lifecycle. Policy recovery/expiry does not silently reselect or restart the
camera: the student must choose and enable it again. Microphone use still
requires its own consent and is not prohibited by a camera-only accommodation.
The existing server scoring exemption and penalty-free opt-out are retained.

Deploy the backend endpoint together with the frontend. An older/unreachable
backend leaves the camera off rather than treating a failed lookup as permission.
No database migration or new media upload/storage is introduced.

## Dependency checks

The existing `Shezin-Vite-Patch` commit is reused, preserving attribution. The
lock now resolves Vite 8.1.6. The upstream [Vite advisory](https://github.com/vitejs/vite/security/advisories/GHSA-rq7h-c2jc-7f22)
lists that release as patched for the affected 8.1 line. These findings concern
development-server configurations; they are not evidence of compromise of the
built nginx application. Use the documented built deployment for demos, not a
public Vite development server.

Fresh local checks on 9 November 2026:

- `npm audit --json`: zero reported vulnerabilities, including development tools.
- `npm audit --omit=dev --json`: zero reported vulnerabilities.
- A freshly resolved backend `[dev]` environment plus pip-audit 2.10.1: 87
  installed dependency versions audited, zero known vulnerabilities reported.

The **Dependency audit** workflow runs on pushes and PRs. Frontend checks retain
separate full/production JSON reports and fail at moderate or higher severity.
Backend checks export exact installed versions, exclude only the editable local
application, and audit the complete resolved list with
[pip-audit](https://github.com/pypa/pip-audit). They fail on findings or incomplete
strict audits. Reports and resolved Python versions are uploaded even when a
scan fails. No blanket advisory exclusions are configured.

Backend CI covers the default runtime and development dependencies. Optional
extraction/transcription extras and externally hosted models/containers need
scanning in the actual deployment environment when enabled; these results do
not certify configurations that were not installed. To repeat against that
actual environment, install its extras, export `pip freeze --exclude-editable`,
and audit the complete pinned list with `pip-audit --disable-pip --no-deps`.
The Python resolver currently uses the project's declared ranges, so CI retains
its exact resolved versions rather than claiming a permanent lock file.

When a check fails, inspect the artifact for affected package/version, advisory
and patched versions; determine runtime versus build-tool exposure, update the
smallest supported dependency set, then rerun scans and regression checks.
An advisory-service/network failure is an incomplete scan, not a clean result.

## Regression evidence

- `backend/tests/test_consideration.py`: overlapping approvals, inclusive expiry,
  longer unrelated approvals, later pending requests, private notes, legacy
  records and staff denial.
- Route/consent/security inventories cover the new private endpoint; existing
  engagement/fairness tests verify scoring accommodations remain effective.
- `frontend/e2e/student.spec.ts`: saved consent with/without monitoring consent,
  remote camera-off decisions during a delayed permission result, lookup failure
  and recovery, fresh authorization before manual starts, and stop/unmount/
  disconnect while consent verification is pending. Existing local-sensor tests
  continue to cover cancellation, real model startup, derived-only payloads and
  shutdown in branded Chrome/Edge CI.

Automated tests use synthetic data. Real Teams, hardware and human accessibility
acceptance in #160/#239 remain separate and are not marked completed by this PR.
