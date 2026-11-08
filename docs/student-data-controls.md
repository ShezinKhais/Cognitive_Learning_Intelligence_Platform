# Student data controls — issue #170

Students open **My data** from their student navigation or the consent page.
The route `/student/my-data` requires a signed-in student but remains available
after terms withdrawal. Signing in from its direct link returns to that page.
Lecturers and administrators cannot use this own-student screen.

**Download my data** retrieves the existing own-data JSON export. The screen
shows preparation, errors and download-start confirmation. A failed API call or
browser download can be retried. Export and request-status reads explicitly use
`cache: no-store`; the API also returns private/no-store responses. The only
intentional saved copy is the file the student downloads. It is their
responsibility to keep or remove that file safely.

**Ask to erase my data** shows an irreversible-erasure warning, an optional
500-character reason and an explicit checkbox. Filing a request does not delete
anything: the existing administrator approval and execution process still applies.
While submission is pending, send/cancel/reason/confirmation controls cannot
start another operation. If a conflict or lost response occurs, the UI checks
whether an open request already exists instead of automatically repeating the
POST. The existing backend uniqueness constraint remains the final safeguard.

The latest request status can be retried manually and refreshes every 30 seconds
while the page is visible, and on window focus. An unsent reason survives a
failed status refresh. Sending is blocked while status is unavailable. Old
in-flight reads are cancelled when a submission confirms a newer request.
An expired access token uses the existing cookie renewal; a refused session
shows a sign-in link that preserves the My data destination.

## Implementation and ownership

This completes the AI2 frontend/integration work on top of #176 and extends
#179. It uses the existing BBIS endpoints without schema or backend workflow
changes:

- `GET /api/v1/me/data`
- `GET /api/v1/me/deletion-request`
- `POST /api/v1/me/deletion-request`

Admin approval, execution, erasure, audit and retention logic are unchanged.
Merge #176 before retargeting/merging #179 into main. Keep #170 open until the
PRs are integrated and the target deployment has been verified. No test-plan
or RTM ownership is transferred; this report supplies AI2 evidence for it.

## Validation — 7 November 2026

Based on #176 `d746a0e` with the #179 changes and the issue-170 implementation.
Synthetic accounts and disposable data only; no actual student records were used.

| Check | Result |
| --- | --- |
| Frontend unit tests | 239 passed |
| My data browser regressions | 7 Chromium cases passed |
| Deployed browser journeys | 4 Chromium journeys passed |
| Own-data/deletion backend regressions | 30 passed, 1 existing external-tool-dependent skip |
| Build, frontend lint, browser TypeScript, backend Ruff and contract snapshot | Passed |
| Mobile layout / keyboard / automated WCAG A/AA | Passed at 375 × 812 in the My data harness |

Browser regressions cover initial status failure/retry, unsent-reason retention,
conflicts from another tab, pending-submission controls, administrator status
refresh on focus, browser download failure, expired-token renewal/refusal, a
lost response after a committed POST, and mobile keyboard use. Those tests use
controlled API responses to exercise failures deterministically.

The deployed journeys use real browser → nginx → backend → PostgreSQL with
current source mounted into an isolated container stack and the current Vite
production bundle mounted into nginx. They verify student/lecturer/admin
sign-in, role pages, reload, sign-out and staff denial of My data. The student
journey runs at 375 pixels, withdraws terms, follows the consent-screen My data
link using the keyboard, downloads JSON with `no-store`, files a confirmed
request, verifies duplicate controls are absent, then signs out through the
mobile menu and signs back into the direct My data link.

Backend tests verify the existing own-student data isolation and deletion
approval behavior. No backup restoration or real production erasure is claimed.
A real Teams tenant, physical devices, human screen-reader acceptance and the
institution's target deployment were not part of this isolated run. Branded
Chrome/Edge results are provided by the PR's CI run.
