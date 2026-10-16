# Student client validation on the combined integration code

Date: 2026-10-16. Base: integration candidate #158 at `a2fd33e`.
Branch: `ai2-student-client-validation`. This is not a new umbrella PR and does
not change main, #158 or teammates' branches. It reuses #150's isolated test
harness and its two chat fixes, then adds tests and one contrast fix.

## Reproduced problems and fixes

- On unmodified #158, IME composition Enter submits an unfinished chat message.
  The first Linux browser run had **13 pass / 1 fail**, failing on a real chat
  request after composition Enter. Reused #150's composition guard and its
  reduced-motion instant-scrolling fix; the combined keyboard/IME/motion test
  passes afterward.
- The new axe WCAG scan found the chat disclaimer had **4.44:1** contrast
  (`#6b6b85` on `#ededf7`), below the expected 4.5:1. Its text now uses the
  foreground colour. Narrow-width/streaming, dark and high-contrast scans pass.

The original #158 still needs these client changes: this validation branch is
not a deployment. Coordinate with #150 rather than merging duplicate test work.

## Automated evidence

The actual attention/chat components are built into a separate test entry;
consent/user APIs are mocked and camera/audio tracks are synthetic. MediaPipe
and Silero/ONNX inference are real local runtimes, not mocked inference.

| Check | Coverage / result |
|---|---|
| Mac Chrome launch | Aborts before a page opens (SIGABRT); not a browser pass |
| Linux ARM64 Chromium | Runner works using `mcr.microsoft.com/playwright:v1.64.1-noble`, browser 156.0.8078.4 |
| Opt-in / permissions | No device before saved opt-in and explicit enable; injected camera/mic denial, failed consent save, pending-request cancellation and late-stream release |
| Local models | Real self-hosted model startup with fake camera/audio; non-null derived observations required; failed face/VAD asset loading releases tracks |
| Privacy teardown | Disable, camera stop while mic continues, disconnect, unmount, consent rejection, remote monitoring withdrawal, failed consent recheck, hidden page and pagehide |
| Sensor boundaries | Exact four-field summaries, unavailable fields remain null, bounded window; no external runtime requests in startup tests |
| Synthetic slower CPU | 4x CDP throttling; camera startup measured 955 ms, microphone 4,950 ms in the expanded diagnostic run. These are synthetic measurements, not real-device guarantees |
| Keyboard / motion | Opt-in/save/enable/disable, chat ask/cancel, partial text retained, Shift+Enter, IME composition and reduced-motion scrolling |
| Accessibility | Axe WCAG 2 A/AA and 2.1 AA scans: initial/streaming state at 320 px and idle dark/high-contrast themes; no detected violations after the notice fix |
| Unit/build | 94 frontend tests, lint and production build passed; browser TypeScript check passed |
| Existing privacy/fairness regression | 92 backend tests passed; not independent Cyber 1 audit approval |

The expanded initial run had 20 pass / 1 fail (the contrast finding). A focused
post-fix rerun passed all 3 WCAG tests. The final complete browser run and
branded Chrome/Edge CI results must be read from their actual outputs; a
configured job is not evidence of a pass.

The branch-only `Integrated student client validation` workflow installs
branded Chrome and Edge in separate jobs and uploads HTML reports, failure
traces, axe results and synthetic performance JSON for 14 days. It runs only
on pushes to this validation branch or manual dispatch. No real media or real
student tokens are used in the artifacts.

## Reproduction

```sh
# frontend/
npm ci
npm test
npm run lint
npm run build
npm run check:browser
npx playwright install --with-deps chrome msedge
npm run test:browser -- --project=chrome --project=edge
```

For the isolated Linux runner, mount frontend at `/workspace`, use a separate
container-only `/workspace/node_modules`, run `npm ci`, then
`npm run test:browser -- --project=chromium`. Browser tests never need the
developer's physical camera/microphone or their browser profile.

## Not signed off by these tests

- Real macOS/Windows OS permission prompts, physical camera/mic failures and
  device indicator behaviour. Injected denial is not an OS permission test.
- Installed Teams meeting side panel/WebView, host iframe permissions, real
  reconnects and tenant identity/authorization. This harness is not Teams.
- Gaze/voice accuracy with consenting humans, lighting, glasses, multiple faces,
  speech/noise, false positives/negatives. Fake camera/silent audio cannot
  measure this, and gaze is not proof of attention or comprehension.
- A physical low-spec machine's memory/thermal/GPU limits or a 10-minute soak.
- Screen-reader interaction, real 200% zoom and full student-session keyboard
  navigation. Axe has limited scope and does not certify WCAG conformance.
- A complete privacy/network audit: the harness receives summaries rather than
  transmitting them through a live classroom. Existing backend schema tests
  reject raw fields, but real deployed transport must still be inspected.
- Cyber 1's independent privacy/fairness review and the existing dependency
  advisories. No security sign-off or forced dependency upgrade is claimed.
