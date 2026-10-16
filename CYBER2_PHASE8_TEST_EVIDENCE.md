
# Cyber 2 Phase 8 Test Evidence

## C.L.I.P. - Staff Interface, Deployment and Accessibility Testing

**Phase:** Phase 8 - Hardening and Delivery

**Workstream:** Cyber Security 2

**Issue:** #74 - P8 Cyber 2: Staff interface, deployment and accessibility testing

**Branch:** `Aliyeh-Phase-8-Cyber-2`

**Evidence updated:** 16 October 2026

**Previous manual checks:** 15 October 2026

## 1. Scope and Boundaries

Phase 8 Cyber 2 is responsible for validating:

- Staff permissions and access controls
- Insecure direct object reference (IDOR) protection
- Report viewing and PDF downloads
- Frontend accessibility
- Local availability and deployment security requirements
- Governance interface presentation
- Staff demonstration workflow and screenshots

Cyber 2 displays backend-authoritative information. It does not generate reports, enforce backend governance decisions, change engagement or comprehension scoring, or process raw sensor media.

The frozen `backend/openapi.json` and `backend/events.schema.json` contracts were not modified for this Phase 8 work. Breakout rooms are outside the agreed scope.

## 2. Automated Testing

### Result: PASS for Executed Tests

The frontend and backend checks recorded below were performed on 16 October 2026.

### Frontend Tests

Commands executed from the `frontend` directory:

```powershell
npm test
npm run build
npm run lint
```

Results:

```text
Frontend tests: 122 passed
Failed: 0
Skipped: 0
Production build: PASSED
Lint warnings: 0
Lint errors: 0
```

The production build completed successfully using Vite 8.1.5, transforming 2,087 modules.

The frontend regression suite includes:

- Authentication and role-routing rules
- Session and report status handling
- Report-download readiness
- Governance deletion-state checks and identifier validation
- Intelligence presentation and source citations
- Teams integration helpers
- Student live-session behaviour
- Report API and PDF response tests
- Report polling request and retry tests

The latest Phase 8 work added 19 frontend tests:

- 12 tests in `frontend/tests/sessionReportsApi.test.ts`
- 7 tests in `frontend/tests/reportPolling.test.ts`

The total increased from 103 to 122 passing frontend tests.

#### Report API and PDF Tests

The 12 new tests exercise the actual frontend API functions against mocked HTTP responses.

Verified scenarios include:

- Authenticated `POST` requests for report generation
- Blocking report requests when no access token exists
- Authenticated report-status retrieval
- Preservation of backend authorization and error messages
- Removal of invalid credentials after HTTP `401`
- Safe handling of non-JSON server errors
- Retrieval of PDF binary data
- Reading the attachment filename from response headers
- Falling back to a default PDF filename
- Blocking unauthenticated PDF downloads
- Preserving PDF HTTP `403` authorization errors
- Preserving HTTP `409` responses when a PDF is not ready

These tests exercise production frontend API functions, rather than only presentation helpers.

They use mocked network responses and do not represent a live browser download or an end-to-end deployment test.

#### Report Polling Integration Tests

The 7 new tests exercise the report polling implementation with the actual frontend status API function and mocked HTTP responses.

Verified scenarios include:

- Polling through queued, running and ready states
- Stopping status checks after a ready response
- Increasing retry delays after temporary server failures
- Stopping after four consecutive failures
- Immediately stopping on HTTP `403`
- Clearing unavailable report state on HTTP `404`
- Handling HTTP `401` without further polling
- Ignoring a response after polling is cancelled
- Preventing a changed or mismatched session from receiving a stale report update

The polling implementation was extracted into:

`frontend/src/features/reports/reportPolling.ts`

The report page now uses this shared implementation:

`frontend/src/pages/LecturerSessionReportPage.tsx`

This improves testability while retaining the report page's generation, refresh, download and presentation responsibilities.

The polling tests use an injectable timer and mocked HTTP responses. They do not mount the rendered React page in a browser.

#### Frontend Quality Checks

The complete suite passed:

```text
122 tests
122 passed
0 failed
0 skipped
```

The production build passed.

The lint command reported:

```text
0 warnings
0 errors
```

`git diff --check` completed without whitespace errors.

### Backend Tests

Commands executed from the `backend` directory with the project virtual environment activated:

```powershell
Remove-Item Env:PYTEST_DISABLE_PLUGIN_AUTOLOAD -ErrorAction SilentlyContinue
python -m pytest -q --tb=short
```

Results:

```text
1,576 passed
279 skipped
0 failed
81 warnings
Duration: 63.90 seconds
```

The skipped tests were not executed in this local run.

The warnings included a Starlette/AnyIO deprecation notice and a development JWT signing key shorter than the recommended length for HS256.

These warnings did not cause test failures. Production JWT configuration must use a sufficiently strong signing key.

A separate focused test run was also completed:

```powershell
python -m pytest tests/test_reports.py -q --tb=short -x
```

Result:

```text
16 passed
0 failed
1 warning
```

The report tests validate backend report-job behaviour and PDF rendering.

An earlier diagnostic run with automatic pytest plugins disabled produced widespread asynchronous-test and fixture errors. Those results were caused by the testing configuration and are not treated as evidence of application regressions.

The backend was not modified as part of the new frontend API and polling test work.

## 3. Staff Permissions and Role Access

### Result: PASS for Tested Access Rules

Frontend role-routing tests confirmed that:

- Students are directed to student pages.
- Lecturers are directed to lecturer pages.
- Administrators are directed to administrator pages.
- Protected routes use consistent role and consent rules.
- Terms consent remains required.
- Authentication failures do not grant access to protected pages.

The new report API tests additionally verified that:

- A report request without an access token is rejected before sending an HTTP request.
- Report-status requests include the bearer token.
- An HTTP `401` response clears stored authentication credentials.
- Backend HTTP `403` and `404` responses are preserved by the frontend API.
- PDF requests without authentication are rejected locally.

These checks cover client-side authentication handling and mocked server authorization responses.

Frontend route guards control the presentation of protected pages.

Backend authorization remains responsible for enforcing security. Frontend checks alone are not a substitute for server-side permission verification.

Full browser-based role-access testing remains outstanding.

## 4. Insecure Object Access / IDOR

### Result: PASS for Tested Backend Behaviour

The focused report-route security tests performed on 15 October reported:

```text
9 passed
0 failed
1 warning
```

The verified behaviour includes:

- The owning lecturer can request and access their report.
- An administrator can access authorized lecturer reports.
- Another lecturer receives `404` when attempting unauthorized access.
- A student receives `403`.
- An unauthenticated request receives `401`.
- Unauthorized report responses do not expose another lecturer's session identifier.
- Unauthorized report access does not reveal the existence of protected reports.

These checks help prevent users from accessing reports by changing report or session identifiers.

The complete backend suite passed again on 16 October.

The new frontend report API tests also verified that protected report requests include authorization headers and that the frontend preserves backend authorization errors.

However, mocked frontend HTTP responses are not independent proof of backend authorization enforcement.

A separate browser-level IDOR demonstration has not yet been recorded.

## 5. Report Generation and PDF Download Security

### Result: PASS for Backend Tests and Frontend API/Polling Tests

The report interface uses the existing backend endpoints:

```text
POST /api/v1/sessions/{session_id}/reports
GET  /api/v1/reports/{report_id}
GET  /api/v1/reports/{report_id}/pdf
```

The backend tests verify:

- Reports can be requested and processed asynchronously.
- PDF downloads are available only after the report is ready.
- An early PDF request receives `409 Conflict`.
- Successful PDF responses use `application/pdf`.
- PDF responses are delivered as attachments.
- Sensitive PDF responses use `Cache-Control: no-store`.
- Students cannot download staff reports.
- Other lecturers cannot access reports belonging to someone else.
- Report access remains controlled by backend authorization.

The frontend API tests verify that:

- The report-generation request uses the correct protected endpoint and HTTP method.
- Status retrieval uses the correct protected endpoint.
- Bearer authentication is included with requests.
- HTTP error responses are converted into frontend API errors.
- The PDF client reads binary response data into a Blob.
- The PDF client obtains the filename from `Content-Disposition`.
- The PDF client uses a fallback filename when needed.
- A missing token prevents a PDF request.
- HTTP `401`, `403` and `409` PDF error responses are handled.

The frontend presents the PDF download action only when the backend reports that the job is ready and includes report data.

The actual browser action that creates an object URL, clicks a download link and revokes the object URL has not been independently tested through a rendered browser workflow.

Cyber 2 does not generate the report contents or render the PDF.

### Phase 7 Review Fixes Included in Phase 8

The Phase 7 Cyber 2 review fixes were incorporated into the Phase 8 branch through merge commit `872436c`, carrying fix commit `bd94cc2`.

These changes include:

- Report polling stops after authorization failures.
- Temporary polling failures use bounded exponential backoff.
- Automatic polling stops after repeated failures.
- Users can manually refresh after polling stops.
- Report state is associated with the active session.
- Stale asynchronous responses are prevented from updating the wrong session.
- Failed report generation can be retried.

### Additional Phase 8 Polling Verification

The new polling tests exercise actual API request handling using mocked HTTP responses rather than only polling calculations.

The verified automated workflow includes:

1. Polling a queued report.
2. Polling while report generation is running.
3. Receiving a ready response and stopping further scheduled polls.
4. Retrying temporary failures using bounded delays.
5. Stopping polling after four consecutive failures.
6. Stopping immediately on permission or authentication failures.
7. Handling expired or unavailable reports.
8. Ignoring cancelled or stale session responses.

The report page has been updated to use the tested polling implementation.

The existing report-generation, manual-refresh, PDF-download and report-display functions remain part of the page.

All 122 frontend tests, the production build and lint passed after these changes.

A rendered-component or browser-level end-to-end test of the full report-generation and PDF-download journey is still pending.

The final live report-ready and browser-download workflow has not been claimed as completed.

## 6. Governance Interface and Integration

### Result: FRONTEND IMPLEMENTED - BACKEND INTEGRATION PENDING

The Phase 7 Cyber 2 governance interface is included in the Phase 8 branch.

Implemented frontend controls include:

- Confirmation before irreversible session deletion.
- Confirmation before retention purge execution.
- Deletion-request pagination beyond the first 50 items.
- Audit-log pagination using the last applied filters.
- Separate selected and applied filters.
- Retention wording based on the configured `retention_days`.
- UUID-structure validation for deletion targets.
- Frontend prevention of approving one's own deletion request.
- Separate loading and error states.
- Prevention of unsupported student-deletion execution.

The frontend self-approval check improves the interface but is not a security boundary.

The governance backend must independently reject self-approval and enforce all authorization rules.

Final testing depends on the availability of the agreed `/api/v1/governance/*` endpoints and their integration into the main backend.

End-to-end retention, deletion and audit-log behaviour must not be marked as passed until those endpoints are available and tested.

Cyber 2 will not implement missing backend governance routes or modify frozen API contracts.

## 7. Frontend Accessibility

### Result: PASS for Previous Manual Local Checks

Manual keyboard checks were recorded on 15 October 2026.

The reviewed interfaces included:

- Administrator console
- Governance interface
- Lecturer materials interface
- Lecturer sessions interface
- Live-session workspace

Observed behaviour included:

- Visible keyboard focus
- Usable Tab navigation order
- Keyboard-operable links and buttons
- Readable control labels
- Important states communicated through text rather than colour alone
- Readable error messages
- Explicit confirmation controls for irreversible governance actions

These are local manual observations.

They should not be presented as a complete WCAG accessibility audit.

A further automated accessibility audit and integrated browser-level screen-reader and ARIA verification remain useful before final delivery.

## 8. Local Deployment Baseline

### Result: PASS for Previously Observed Local Availability

The local frontend and backend were checked on 15 October 2026.

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

These results confirmed that:

- The local frontend was reachable.
- The local backend API was reachable.
- Backend request tracing was active.

This is evidence of local availability only.

It does not confirm production deployment or production security headers.

## 9. Production Security Headers

### Result: PENDING FINAL DEPLOYMENT

The final production environment must be served over HTTPS.

Microsoft Teams embedding requires an appropriate HTTP Content Security Policy response header.

Required Teams framing policy:

```http
Content-Security-Policy: frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com https://*.cloud.microsoft;
```

This policy must be configured as an HTTP response header rather than relying on an HTML meta tag.

The deployed environment must be checked for:

- HTTPS
- Content-Security-Policy
- Teams-compatible `frame-ancestors`
- Absence of conflicting `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Strict-Transport-Security` where applicable
- Appropriate caching rules for sensitive responses

Final hosting and production response headers have not yet been verified.

Deployment integration remains dependent on the workstream responsible for hosting.

## 10. Session Readiness Behaviour

### Result: PASS for Previously Observed Behaviour

During the lecturer workflow check on 15 October, the live-session interface displayed the backend content-readiness state.

Observed values:

```text
Materials: 2
Deliverable questions: 0
Processing: 0
Failed materials: 0
```

The session correctly refused to start because no approved question had been staged.

The interface displayed:

```text
Stage at least one approved question before starting the session.
```

This reflects the AI 1 Phase 4 content-readiness requirement.

Cyber 2 displays the backend decision and does not bypass or redefine the readiness rule.

A separate proposal to permit sessions without staged questions requires an explicit team requirements decision. It is not assumed to be approved or merged.

## 11. Staff Demonstration Workflow

### Result: IN PROGRESS

Previously verified areas include:

- Lecturer authentication
- Lecturer sessions navigation
- Session creation
- Navigation to the live-session workspace
- Backend readiness-state presentation
- Availability of protected report navigation

The latest automated tests additionally verify report API and polling behaviour using mocked HTTP responses.

The following final workflow checks are still pending:

- Complete a session with staged questions.
- Request generation of a session report against the running backend.
- Confirm that the report progresses to the Ready state.
- Download the generated PDF through the browser.
- Open and verify the downloaded PDF.
- Test governance actions against the integrated backend.
- Verify the final deployment security headers.
- Capture final interface screenshots for the report or poster.

These steps must be completed before the full demonstration workflow can be marked as passed.

## 12. Current Phase 8 Status

| Area | Status |
|---|---|
| Frontend regression tests | PASS - 122/122 |
| New report API/PDF tests | PASS - 12/12 |
| New report polling tests | PASS - 7/7 |
| Frontend production build | PASS |
| Frontend lint | PASS - 0 warnings, 0 errors |
| Full backend regression tests | PASS - 1,576 passed; 279 skipped |
| Backend report tests | PASS - 16/16 |
| Previous report authorization/IDOR tests | PASS - 9/9 |
| Frontend role guards | PASS within tested scope |
| Report polling retry and failure handling | PASS - automated API-based polling tests |
| Report stale-session protection | PASS - automated polling tests |
| Frontend report API authentication and errors | PASS - mocked HTTP tests |
| Frontend PDF response handling | PASS - mocked HTTP tests |
| Governance frontend controls | IMPLEMENTED |
| Rendered-component/browser API/PDF end-to-end testing | PENDING |
| Manual keyboard accessibility | PASS for previous local checks |
| Comprehensive accessibility audit | PENDING |
| Local frontend availability | PASS for previous local checks |
| Local backend availability | PASS for previous local checks |
| Backend request tracing | PASS for previous local checks |
| Session readiness presentation | PASS for previous local checks |
| Production HTTPS/CSP/Teams headers | PENDING DEPLOYMENT |
| Governance backend integration | PENDING BACKEND |
| Backend self-approval enforcement | PENDING VERIFICATION |
| Complete staff demo workflow | IN PROGRESS |
| Final interface screenshots | IN PROGRESS |

## 13. Conclusion

Phase 8 Cyber 2 incorporates the completed Phase 7 Cyber 2 review fixes and additional frontend API and polling verification.

On 16 October 2026:

- All 122 frontend tests passed.
- Twelve new report API and PDF tests passed.
- Seven new report polling integration tests passed.
- The frontend production build completed successfully.
- Frontend lint reported zero warnings and errors.
- The backend test suite completed with 1,576 passed, 279 skipped and zero failures.
- The focused backend report test suite passed all 16 tests.
- Previous focused report-route authorization tests passed all 9 tests.

The additional tests directly exercise frontend report requests, authentication handling, PDF response processing, status polling, retry behaviour, authorization failures and stale-session protection against mocked HTTP responses.

This improves coverage beyond helper-only tests and addresses the frontend API/polling testing concern raised during review.

However, Phase 8 is not yet fully verified for deployment.

Outstanding work includes a rendered-component or browser-level end-to-end report and PDF workflow, final governance-backend integration, production HTTPS and Teams security-header verification, the complete staff demonstration, and final screenshots.

These remaining checks must be completed and recorded before the integrated Phase 8 deliverable is described as fully complete.
