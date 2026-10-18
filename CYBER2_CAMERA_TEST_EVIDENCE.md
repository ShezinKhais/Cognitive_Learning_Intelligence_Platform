# Cyber 2 Camera Attention Acceptance Evidence

GitHub issue: #160
Branch: Aliyeh-P8-Cyber2-Camera-Acceptance
Test date: 2026-10-18
Environment: Windows, localhost development frontend and backend

## Scope

Acceptance testing of optional browser-local camera and microphone
indicators, student consent, shutdown, privacy, browser compatibility,
lecturer visibility, and Teams lecturer routing.

The new continuous camera-away timer is local display state. It is not
transmitted to the backend or used as a disengagement score.

## Automated verification

- Frontend unit/proxy tests: 109 passed.
- Away-duration helper tests: 4 passed.
- Teams integration tests: 9 passed.
- TypeScript production build: passed.
- Frontend lint: 0 errors and 0 warnings.
- Git whitespace check: passed.

The reported test counts come from their respective runs and should
not be added together without accounting for overlapping tests.

## Chrome manual acceptance

- Camera-only opt-in and activation: passed.
- Disable all stops camera and clears timer: passed.
- Blocked camera permission prevents activation: passed.
- Revoking camera permission while active stops sensing: passed.
- Switching away from the tab stops camera sensing: passed.
- Returning to the tab does not automatically restart sensing: passed.
- Keyboard navigation, checkbox operation and buttons: passed.

## Microsoft Edge manual acceptance

- Camera activation: passed.
- Camera shutdown and timer clearing: passed.
- Microphone-only sensing: passed.
- Camera remains off with microphone-only opt-in: passed.
- Microphone stops after Disable all: passed.

## Network privacy

Chrome Developer Tools was used to inspect the live-session socket.

- Outgoing signal.attention messages were observed.
- Inspected data payload contained the four approved fields:
  gaze_on_screen_ratio, face_present, speaking, window_seconds.
- The local away-duration timer was absent from the inspected payload.
- No raw video or audio was present in the inspected attention messages.
- face_landmarker.task was served from 127.0.0.1:5173.
- MediaPipe WASM JavaScript and binary were served from 127.0.0.1:5173.
- The face worker was loaded by the frontend.

This is evidence for the inspected requests and messages, not a
complete network-wide traffic audit.

## Lecturer and Teams checks

- LecturerAttentionPanel is already rendered in LecturerLiveSessionPage.
- TeamsLecturerMeetingPage redirects to that lecturer workspace after
  resolving the session.
- Nine Teams routing/integration tests passed.
- Real Teams web and desktop acceptance remain untested.
- Lecturer panel showed one student with insufficient data and 0%
  evidence coverage during camera/microphone-only testing.
- Backend staff_confidence intentionally reflects participation
  evidence, not camera-only evidence; this was not treated as a
  disengagement failure.

## Known limitations and outstanding acceptance

- Head tilt can cause the camera-away timer to count even when the
  student is looking at the screen.
- Looking down and gaze estimates are unreliable in tested scenarios.
- Head-pitch/gaze accuracy work belongs to Issue #159 (Luna).
- Screen-reader announcements with Windows Narrator are unconfirmed.
- Real Teams web/desktop behaviour has not been manually tested.
- Lower-spec device performance has not been benchmarked.
- Camera permission granted after a pending permission-dialog shutdown
  has not been manually verified.
- Wider device/browser acceptance remains pending.

## Release and integration boundaries

VITE_LOCAL_ATTENTION_ENABLED remains false by default. Camera testing
used a temporary per-terminal environment variable.

The attention WebSocket contract remains unchanged.

This evidence supports a draft pull request, not unconditional
production or real-Teams deployment approval.

The branch must be checked against current origin/main before merging.
