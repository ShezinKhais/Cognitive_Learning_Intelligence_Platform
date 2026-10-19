# Post-merge integration audit — 2026-10-19

PR #161 integrates main through `297ee10`, including #162/#163 governance,
#164's web shell and cookie sign-in, and #167's camera/calibration fixes.
This supersedes the older audit's current-status statements. It is evidence
of tested paths, not a promise that every feature is complete or bug-free.
No unmerged work from #168 is included.

## Changes

- Kept #164's memory-only access token, httpOnly refresh cookie, CSRF header,
  shared `renewSession`, outage/retry distinction and awaited cookie logout.
  Removed the superseded bearer-refresh helper instead of running two recovery
  mechanisms. Updated socket tests to use the real memory credential contract.
- Fixed all three socket handshakes (student, lecturer, material progress):
  after sign-out they must not fall back to a captured token. Each handshake
  uses the current credential; a stopped effect never authenticates a late socket.
  Tests cover refresh, temporary offline/503, definitive refusal, bounded
  retries, sign-out and reconnect.
- Connected the existing student room control to validated, active/unpaused
  submission. A sent event is not a server-confirmed room assignment.
  Reconnect preserves typed text but never silently resends it.
- Preserved the new governance/consideration/material-edit route inventory
  and withdrawn-consent student data rights in the security audit. Removed
  obsolete 501 allowances; created-resource tests verify session/summary data.
  The bootstrap test now exercises real login, cookie refresh and identity.
- Cancelled sessions no longer offer an ended-session review.
- Updated compatible transitive build dependencies: `nanoid` 3.3.20 and
  `source-map-js` 1.2.2. The resulting npm audit reports no vulnerabilities.
- Extended the external deployment smoke check with cookie scope/httpOnly,
  missing-CSRF-header denial, refresh without a bearer, identity and logout.
  Added opt-in browser tests against the real deployed three-role shell.

## Connections and ports

| Mode | Browser entry | API and WebSocket destination | Database/model |
| --- | --- | --- | --- |
| Local development | Vite 5173 | Vite forwards both `/api/` and `/ws/` to `CLIP_BACKEND_URL` (default backend 8000) | Dev PostgreSQL 5432; Ollama 11434 |
| Local preview | Vite 4173 | Same backend proxy setting as development | Same configured backend dependencies |
| Docker demo | nginx 8088 by default (`DEMO_PORT`) | nginx serves SPA and forwards to internal `backend:8000` | Internal `db:5432`; configured Ollama endpoint |
| This isolated smoke run | nginx 18088 | Same real nginx/backend configuration | Separate Compose database/volumes; not the user's dev DB |

These ports are intentionally different. No browser connects directly to
PostgreSQL or needs an API-specific frontend origin. REST, streamed chat and
both WebSocket channels share the browser origin. Dev and preview proxy tests
also send real HTTP bodies/authorization and upgrade a WebSocket to a custom port.
TLS is still required for production, real Teams and non-localhost media.

## Verification

- Fresh PostgreSQL database `clip_pr161_integrated_20261019`, all migrations
  through `e1f2a3b4c5d6`: **2,955 backend tests passed, 6 skipped, 1 failed**.
  The failure is the existing Mac LibreOffice WMF-to-blank-image case, not
  an integration regression; it was not disabled or weakened. Skipped checks
  require optional external tools/fixtures; CI and deployment acceptance
  remain necessary. No development database was migrated or cleared.
- **212 frontend unit/proxy tests passed**; production build, lint,
  browser TypeScript checks and backend lint/format/contract checks passed.
- **49 Chromium browser tests passed**, including socket recovery and
  local-AI/permission/privacy/accessibility scenarios with synthetic media.
  **3 real deployed-browser role workflows passed** through nginx, including
  cookie reload/logout, student staff-page denial and no browser/API 5xx errors.
  The new `deployment-integration` CI job rebuilds and tests the same stack;
  branded Chrome/Edge and full CI status must be checked on the pushed commit.
- Live-to-review database integration verifies discovery, role denial,
  WebSocket room selection, question delivery, accepted answer, feedback,
  persistence, session end and matching review/summary counts with no-store.
  Missing historical engagement stays unavailable, not zero.
- The isolated three-container deployment built and started healthy.
  External smoke checks passed through nginx: SPA/deep links, API errors,
  database readiness, lecturer/student login and consent, WebSocket
  authentication/ping and cookie refresh/logout. Models and Teams are not
  required for this smoke test.

To repeat the deployed browser tests, first start a disposable **development**
demo stack following [deployment.md](deployment.md). They sign into the demo
accounts and record terms consent, so do not target production or real data:

```sh
cd frontend
CLIP_DEPLOYMENT_TEST_URL=http://localhost:8088 npm run test:deployment
```

Install Playwright Chromium first if needed. No server is started automatically;
the test refuses to proceed unless the health endpoint reports development.
The tests do not request a camera or microphone.

## Remaining release gates and scope boundaries

- **Admin imports and multi-course enrolment:** current upload handlers still
  validate/match rather than persist dated sessions/enrolments. This needs the
  agreed database contract, dates/timezone and owner implementation; no silent
  student reassignment or fabricated sessions were added.
- **Full group formation:** student room reporting and live room activity are
  connected, but lecturer group recommendation/edit/finalization and actual
  Teams room moves are not supplied by #161. The shell's group preview is not
  a production workflow.
- **Historical engagement:** governance semester history does not by itself
  provide a consent-aware, confidence/availability-qualified per-session
  engagement timeline. The student review must not invent one.
- **Retention/governance:** merged main now defaults to the agreed **120 days**
  and includes Nour's implementation. Optional history storage, scheduled
  backups and restore exercises still require operator configuration; a demo
  stack with no history URL does not prove a separately deployed history DB.
- **Real Teams:** tenant registration, permissions, identity mapping, HTTPS,
  real notifications and meeting lifecycle need tenant acceptance. Mock tests
  cannot establish delivery.
- **Devices and AI quality:** synthetic media verifies local asset loading,
  permission failure, cleanup and coarse output privacy, not human gaze/VAD
  accuracy, assistive-technology acceptance or Teams-webview compatibility.
  Live Ollama retrieval/grounding and supported OCR/vector converters require
  deployment checks. See the owners' evaluation reports.
- **Durability:** classroom state and background jobs remain single-process;
  this is not a crash-durable distributed queue or multi-worker deployment.

The merged reporting, governance and camera work is preserved, not replaced.
No extra implementation of Aliyeh's or Nour's pending work was taken over.
