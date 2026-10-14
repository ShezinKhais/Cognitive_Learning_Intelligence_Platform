# Phase 8 AI2 — student interface and client-AI test report

## Scope and status

Baseline: `main` at `5ddc0a3`. Tests mount the actual student attention controls
and Socratic chat components in a separate production-bundled harness. This is
component integration evidence, not a full authenticated student-session or
Teams deployment certification. Phase 7 student review PR #140 is not in this
baseline; repeat student-review navigation/source-link checks after it merges.

Two defects fixed: chat smooth scrolling ignored reduced-motion preferences;
Enter during IME composition submitted an unfinished question.

Local validation (2026-10-14, macOS, Node 24.19.0):

- `npm test`: **90 passed** (including gaze proxy, stale/missing signals,
  summary shape, chat protocol and Teams theme/context tests).
- `npm run build`: **passed**, including TypeScript project compilation.
- Browser harness production build: **passed**.
- `npm run lint` and separate browser-test TypeScript compilation: **passed**.
- Installed Chrome launch: **blocked by execution sandbox** (SIGABRT before
  any page/test executed). This is not a passing browser run.
- Chrome and Edge browser results: see the PR's `student-browser` CI jobs and
  their retained HTML reports, failure traces and synthetic performance JSON.
  Initial commit `089a7b8` passed **14/14 in Chrome 155.0.8059.79** (28.3s)
  and **14/14 in Edge 155.0.4283.45** (27.1s), without retries, on Ubuntu
  24.04.5 / Node 24.21.0. [Verified run](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/actions/runs/38609375369).
  Subsequent runs additionally require a non-null inference observation and
  print synthetic startup measurements to the log for durable evidence.
  A configured test is not evidence of a pass until that job succeeds.

## Repeatable automated coverage

| Area | Evidence / limits |
| --- | --- |
| Chrome / Edge | Same Playwright suite in separate CI jobs using branded browsers, not a renamed Chromium project. |
| Permission flow | No capture before saved consent and explicit enable; camera/mic denial; failed consent save; cancellation while permission is pending and late-stream release. Denial is injected, not an OS prompt test. |
| Privacy shutdown | Real synthetic tracks end on disable, disconnect, unmount, rejected consent, pagehide and simulated document hidden. |
| Local AI | Actual self-hosted MediaPipe and Silero/ONNX startup with synthetic browser media; missing face model failure releases tracks. No mocked inference runtime in startup tests. |
| Slower CPU | CDP 4x CPU throttling, startup duration attached per sensor, and at least one derived summary within 15 seconds after readiness. This is a regression smoke budget, not an accuracy or real-device latency claim. |
| Raw-media boundary | Summary keys restricted to the four derived fields; startup test records browser-context requests (including workers) and rejects external runtime requests. This does not replace a full network/privacy audit or backend transport test. |
| Keyboard | Native opt-in controls, save/enable, disable, chat submission and streaming cancellation; Shift+Enter and IME Enter do not submit. |
| Reduced motion | With reduced-motion emulation, streamed chat update scroll requests are immediate rather than smooth. Existing CSS reduces animation/transition duration. |
| Chat | Source metadata/excerpt rendering and incremental response cancellation retaining partial text. |

The harness uses fake camera/audio browser flags and stubbed consent/user APIs;
it must never require a developer's real camera, microphone or production token.
It is a separate Vite entry and output (`dist-e2e`), excluded from the normal
application build. The slow NDJSON endpoint exists only in the test preview
configuration. No changes to server consent or production model behavior.

## Reproduction and artifacts

From `frontend`:

```sh
npm ci
npm test
npm run lint
npm run build
npx playwright install --with-deps chrome msedge
npm run test:browser -- --project=chrome --project=edge
npx playwright show-report
```

The optional `chromium` project requires `npx playwright install chromium`.
`test:browser` builds the isolated fixture and starts localhost port 4174 itself.
CI uploads `student-browser-chrome` and `student-browser-edge` artifacts for
14 days, including JSON startup measurements and traces on failure. Synthetic
media is used, so these artifacts must not include real student data.

## Manual release gates — NOT EXECUTED

Record tester/date, OS, exact browser/Teams version, CPU/RAM, outcome and
sanitized evidence for each row. Do not mark Phase 8 completely signed off
until these checks and CI are complete.

| Environment | Procedure and acceptance |
| --- | --- |
| Chrome and Edge desktop | Join a real test session. Deny then allow each device in browser/site and OS settings, including permission prompt dismissal. Class participation remains usable; denied signals stay unavailable, not zero attention. |
| Teams web and desktop WebView | Open actual installed meeting side panel. Repeat permissions, reconnect, hide/restore, theme/high contrast and keyboard checks. Verify iframe/host permission policies and that sensing never silently resumes. Ordinary browser testing does not prove Teams behavior. |
| Lower-spec physical device | Run a 10-minute synthetic/test-account session with both sensors. Record hardware, startup, CPU/memory, visible UI responsiveness and summary gaps. Disable promptly; verify camera/microphone indicators turn off. CPU throttling alone cannot model RAM, thermals or GPU limitations. |
| Gaze / voice accuracy | With consenting testers, check face absent, looking away, closed eyes, multiple faces, glasses/lighting variations, silence, speech and background noise. Record expected vs observed summaries and false positives/negatives without storing raw media. Gaze is only a coarse proxy, never proof of comprehension. |
| Accessibility | Keyboard through the complete student session and post-session review; no trap, visible focus, logical order. Screen-reader labels/status and OS reduced motion, at 200% zoom and narrow Teams width. Verify media are optional for all learning tasks. |
| Privacy | Inspect network during capture and disable; only authorized summary transport, no image/audio/landmarks. Revoke consent remotely, wait for recheck, confirm teardown; repeat reconnect and model-load failure. |

## Repository-wide CI blocker outside this frontend change

The initial run's backend job reports **4 failed, 1843 passed, 1 skipped**.
No backend files or backend CI steps differ from baseline in this PR.
The failures are in existing Phase 6 integration tests:

- `test_engagement_fairness_live.py`: three expectations assume three baseline
  samples; the current signal window rate limiting retains only one in their
  sub-second test sequence (including the scorer's normalization expectation).
- `test_privacy_verification.py::test_no_table_stores_a_raw_attention_reading`:
  its blanket column-name prohibition rejects the existing
  `attention_signal_summary.gaze_on_screen_ratio` aggregate column.

[Backend failure evidence](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/actions/runs/38609375369/job/116008466331).
These require a separate reconciliation of the backend timing/privacy tests
with the merged summary feature. This PR does not weaken those tests or change
retention/scoring policy to make CI green. Overall project CI is **not** signed off.

Known separate dependency risk: `npm audit` reports high-severity transitive
build-tool advisories (including nanoid/source-map-js) in the baseline dependency
tree. No automatic major dependency upgrades were bundled into this test PR;
these need separate triage. This report is not a security sign-off.
