# Cyber 2 Phase 8 Test Evidence

## C.L.I.P. - Staff Interface, Deployment and Accessibility Testing

**Phase:** Phase 8 - Hardening and Delivery
**Workstream:** Cyber Security 2
**Issue:** #74 - P8 Cyber 2: Staff interface, deployment and accessibility testing
**Branch:** `Aliyeh-Phase-8-Cyber-2`
**Test date:** 15 October 2026

## 1. Scope

Phase 8 Cyber 2 is responsible for testing:

- staff permissions
- insecure object access
- report downloads
- deployment security headers
- frontend accessibility
- staff demo workflow
- interface screenshots for final delivery

The frozen API contracts in `backend/openapi.json` and `backend/events.schema.json` were not modified as part of this testing.

## 2. Staff Permissions and Role Access

### Result: PASS

Frontend role-routing tests confirmed that:

- students are returned only to student pages
- administrators are returned only to administrator pages
- lecturers are returned only to lecturer pages
- the same role and consent access rule is used by the frontend guards
- terms consent remains required
- authentication failures are handled without exposing protected pages

### Evidence

Frontend test suite:

```text
tests: 100
pass: 100
fail: 0
skipped: 0
```

The protected frontend routes use role guards before protected staff pages are rendered.

## 3. Insecure Object Access / IDOR

### Result: PASS

The report route security tests verify that a lecturer cannot access another lecturer's report by changing identifiers.

The tested behaviour includes:

- the owning lecturer may request and read their report
- an administrator may access lecturer reports
- another lecturer receives `404`
- a student receives `403`
- an unauthenticated request receives `401`
- a real unauthorized report ID returns the same outward response as a non-existent report ID
- unauthorized report responses do not expose the associated session ID

This prevents report identifiers from being used to discover another lecturer's session or report.

### Evidence

Command:

```text
pytest tests/test_report_routes.py -q -rs
```

Result:

```text
9 passed, 1 warning in 3.33s
```

The warning was a Starlette deprecation warning and was not a failed security test.

## 4. Report Download Security

### Result: PASS

The report tests verified:

- PDF downloads are available only after the report is ready
- an early PDF request receives `409 Conflict`
- a successful PDF response uses `application/pdf`
- downloaded PDF responses use `Cache-Control: no-store`
- the PDF is returned as an attachment
- students cannot download staff reports
- another lecturer cannot download another lecturer's report
- report access remains protected by backend authorization

The frontend also only enables PDF download when the backend report job is ready.

## 5. Frontend Accessibility

### Result: PASS - Manual Local Check

The staff interfaces were manually checked using keyboard navigation.

Checked areas included:

- administrator console
- governance interface
- lecturer materials interface
- lecturer sessions interface
- live-session interface

Observed behaviour:

- keyboard focus was visible
- Tab navigation followed a usable order
- links and buttons could be activated using the keyboard
- controls contained visible text labels
- important states were presented using text rather than colour alone
- error messages were readable
- irreversible governance actions use explicit confirmation controls

Automated frontend tests also completed successfully:

```text
100 passed
0 failed
```

## 6. Local Deployment Baseline

### Result: PASS for local availability

The Vite development frontend returned:

```text
HTTP/1.1 200 OK
Content-Type: text/html
Cache-Control: no-cache
```

The backend health endpoint returned:

```text
HTTP/1.1 200 OK
content-type: application/json
x-request-id: 08448704-5489-4545-84fd-1c8723268399
```

This confirms:

- the local frontend is reachable
- the local API is reachable
- backend request tracing is active

## 7. Production Security Headers

### Result: PENDING FINAL DEPLOYMENT

The local Vite development server is not the production hosting environment.

The repository deployment security requirements state that the production frontend must provide a Content Security Policy that allows supported Microsoft Teams hosts to embed the application.

Required Teams frame policy:

```http
Content-Security-Policy: frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com https://*.cloud.microsoft;
```

The final deployed environment must be checked for:

- HTTPS
- `Content-Security-Policy`
- Teams-compatible `frame-ancestors`
- absence of a conflicting `X-Frame-Options` policy
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Strict-Transport-Security` where HTTPS deployment supports it
- appropriate cache behaviour for sensitive responses

Final verification is pending the demo or production deployment owned by the General CS workstream.

This pending deployment check is not treated as a local application failure.

## 8. Session Readiness Behaviour

### Result: PASS

During the lecturer workflow test, the live-session interface correctly displayed the backend content-readiness result.

Observed state:

```text
Materials: 2
Deliverable questions: 0
Processing: 0
Failed materials: 0
```

The session correctly refused to start and displayed:

```text
Stage at least one approved question before starting the session.
```

This behaviour belongs to the AI 1 Phase 4 content-readiness gate and is correctly presented by the Cyber 2 interface.

Cyber 2 does not bypass or redefine this backend rule.

## 9. Demo Workflow

### Result: IN PROGRESS

Verified so far:

- lecturer authentication
- lecturer sessions interface
- session creation
- transition to the live-session workspace
- content-readiness display
- protected Session report navigation is present

Remaining final demo verification:

- complete a session with deliverable questions available
- generate a report from the staff report interface
- confirm report reaches Ready state
- download the generated PDF through the browser
- verify the final deployed workflow
- capture final interface screenshots

## 10. Governance Integration

### Result: DEPENDENCY PENDING

The Phase 7 Cyber 2 governance interface was implemented against the agreed governance contract.

Final end-to-end governance testing depends on the final BBIS governance backend integration.

Cyber 2 must not claim successful end-to-end deletion, retention or audit-log integration until that backend is available and its final API contract has been rechecked.

The interface already includes safety controls such as:

- explicit confirmation for irreversible session deletion
- explicit confirmation for retention purge
- audit-log pagination
- separate loading and error states
- prevention of unsupported student-deletion execution

## 11. Current Phase 8 Status

| Area | Status |
|---|---|
| Staff permissions | PASS |
| Frontend role guards | PASS |
| Insecure object access / IDOR | PASS |
| Report authorization | PASS |
| Report download security | PASS |
| Frontend automated tests | PASS - 100/100 |
| Manual keyboard accessibility | PASS |
| Local frontend availability | PASS |
| Local backend availability | PASS |
| Backend request tracing | PASS |
| Session readiness presentation | PASS |
| Final production security headers | PENDING DEPLOYMENT |
| Final governance integration | PENDING BACKEND INTEGRATION |
| Full final demo workflow | IN PROGRESS |
| Final poster/interface screenshots | IN PROGRESS |

## 12. Conclusion

The Phase 8 Cyber 2 testing completed so far shows that the staff interface enforces role boundaries, protects report objects against unauthorized identifier access, secures report downloads, supports keyboard operation, and correctly presents authoritative backend readiness information.

No frozen API contract changes were required.

The remaining Cyber 2 evidence depends on the final integrated deployment and governance backend. Once those dependencies are available, the production security headers, final governance workflow and final demonstration screenshots must be verified before Phase 8 is marked fully complete.
