# Phase 6 — AI2 local indicators

Implemented behind `VITE_LOCAL_ATTENTION_ENABLED=true` in the student live-session panel (including the Teams panel). The existing live-session feature must also be enabled. Defaults remain off pending integration/device acceptance testing.

## Scope and privacy

- Camera and microphone are separately optional and unchecked initially. Enabling records monitoring/device consent before requesting browser permission. No device starts automatically, including after reconnecting.
- MediaPipe Face Landmarker runs in a dedicated worker. Only coarse face/head/iris-derived observations return to the UI; these are camera-facing proxies, not calibrated eye tracking or evidence of learning/attention. Blinks, malformed landmarks and multiple faces produce unavailable gaze.
- Silero VAD runs through ONNX WASM locally. Only voice-presence booleans enter application state; no transcription, recording, upload or persistent media storage is implemented. The VAD library temporarily buffers audio internally for speech segmentation.
- Every five seconds the existing authenticated socket receives only `gaze_on_screen_ratio`, `face_present`, `speaking`, and `window_seconds` in `signal.attention`. Missing/stale sensors are null, not zero. No media, landmarks or device identifiers are sent. Samples are bounded and cleared after each window; disconnected windows are not queued.
- Disable immediately stops owned tracks and camera worker, including tracks granted after cancellation. Leaving/hiding the page, session pause/end/disconnect, device failure and failed/revoked consent checks stop sensing. Returning never restarts it. Saved consent and an active device are distinct; disabling does not revoke stored consent. Consent is rechecked before each summary.

## Self-hosted assets

`npm ci` followed by `npm run dev` or `npm run build` stages assets automatically. `npm run prepare:attention` can also be run explicitly. Vision WASM, VAD worklet/model and ONNX runtime come from pinned npm dependencies; the version-1 float16 face model is fetched at build time with a pinned SHA-256. Initial preparation needs network access. Subsequent preparation reuses the verified model. Generated `public/attention/` assets are ignored by Git and copied into the deployment by Vite. Deploy the complete build, including these assets, under the configured Vite base path. Serve WASM with `application/wasm`, JS/MJS as JavaScript and model files as binary—not the SPA fallback HTML.

No runtime CDN is required. Use HTTPS (localhost is allowed by browsers), and allow same-origin workers/WASM in the deployment CSP. Embedded Teams/browser hosts may block camera/microphone permissions; the unavailable state is an acceptable fallback and must not prevent participation. No automatic permission-policy bypass is attempted.

### Offline build preparation

The `predev` and `prebuild` asset hooks run even when `VITE_LOCAL_ATTENTION_ENABLED=false`. Before an offline build, install the pinned dependencies and run `npm run prepare:attention` while online, then retain `public/attention/` (including the verified face model) in the build workspace/cache. A fresh offline workspace cannot download the model; the disabled feature flag does not bypass asset preparation.

## Team boundaries

General CS owns transport/aggregation/private prompts; this uses the existing `signal.attention` schema. Cyber 1 owns baseline calibration, signal normalization, accessibility thresholds and privacy verification. BBIS owns persistence. This implementation does not infer engagement scores, issue refocus prompts, penalize missing signals or implement breakout grouping.

## Verification and rollout checklist

Automated: `npm test`, `npm run lint`, and builds with the feature flag both false and true. New tests cover neutral/turned faces, iris position, closed eyes, missing/multiple/malformed faces, null semantics and the derived-only payload shape.

Before enabling production, perform a consented browser/device test (not completed by the coding agent):

1. Join an active session with flags enabled. Confirm zero media permission requests before opt-in. Try camera-only and microphone-only, plus denial, missing hardware and permission revocation.
2. Inspect Network: models/worklets/WASM must be same-origin; WebSocket frames must contain only the four derived fields. Exercise missing models/offline loading and confirm safe unavailability.
3. Disable while a permission dialog or model load is pending, then grant permission: tracks must immediately end. Test individual stop, disable-all, hide tab, navigate away, pause/end session and disconnect. Confirm browser device indicators turn off and no automatic restart occurs.
4. Test normal and Teams views, keyboard controls, multiple faces, dark rooms, glasses, camera off-centre, prolonged speech, and low-power devices. Validate gaze heuristics with Cyber 1 before interpreting them as engagement.
5. Revoke consent elsewhere and verify the next consent check stops sensing. Verify backend consent enforcement independently and confirm no negative inference when readings are unavailable.

Reference implementations: [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/web_js), [VAD browser API](https://docs.vad.ricky0123.com/user-guide/api/).
