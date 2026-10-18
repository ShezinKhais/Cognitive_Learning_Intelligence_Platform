# Camera attention evaluation (Phase 8, AI 1, #159)

How well the browser's camera indicator tells whether a student is looking at
the screen, measured on six team members, before and after tuning. Every
number comes from `frontend/scripts/evaluate-attention.ts`; the full tables
are in [`cv/RESULTS.md`](cv/RESULTS.md) and can be regenerated with
`npm run eval:attention` from `frontend/`.

Nothing in this work changes what leaves the browser: `signal.attention` still
holds only `gaze_on_screen_ratio`, `face_present`, `speaking` and
`window_seconds`.

## What was built

| Part | File | What it does |
|---|---|---|
| Head pose | `frontend/src/features/attention/signals.ts` | Reads real yaw, pitch and roll from MediaPipe's facial transformation matrix, so looking down at notes is not "forward". Falls back to #63's landmark proxies when there is no matrix. |
| Features, then judgement | `signals.ts` (`faceFeatures`, `classifyFace`) | Each frame is turned into a few numbers first and judged second, so recordings can be replayed through exactly the judgement the browser makes. |
| Calibration | `signals.ts` (`calibrate`), `face.worker.ts`, `AttentionControls.tsx` | Optional 3 seconds of looking at the screen sets the student's own centre. Kept in the browser only. |
| Two sets of limits | `signals.ts` (`DEFAULT_THRESHOLDS`, `CALIBRATED_THRESHOLDS`, `thresholdsFor`) | Tuned limits for a student who has calibrated and one who has not. |
| Recorder | `frontend/eval/attention-recorder.html`, `eval/recorder.ts` | Dev-only page (`npm run dev`) that records labelled 10-second clips as numbers per frame, never video, and downloads a CSV. |
| Evaluation | `frontend/eval/evaluation.ts`, `scripts/evaluate-attention.ts` | Leave-one-participant-out tuning and testing, precision, recall, balanced accuracy, clip-level bootstrap intervals. |
| Tests | `frontend/tests/attention.test.ts` | Pose maths, calibration, thresholds, CSV round trip, countdown clean-up, folds, tuning. |

## Test set

Six team members (P1–P6), each consenting on the recorder page, coded by
participant number only. Each clip is 10 seconds at 4 frames per second
(40 frames). Labels acted out: `calibrate`, `screen`, `away_left`,
`away_right`, `down_notes`, `eyes_closed`, `no_face`, `two_faces`.

| Participant | Clips | Conditions recorded |
|---|---|---|
| P1 | 29 | normal, dim, off-centre, far |
| P2 | 7 | normal |
| P3 | 11 | normal |
| P4 | 8 | normal |
| P5 | 7 | dim |
| P6 | 8 | dim and off-centre |

70 clips and 2,801 frames in all. Raw video was never stored; the CSV files
stay with the evaluator and are not committed.

**Cleaning, by hand, before evaluating:**
- P1 downloaded three files without clearing between two of them, so one file
  was an exact repeat of clips in another; the repeat was dropped.
- P2's `two_faces` clip had one face in every frame (no second person), and
  P4's first `two_faces` clip had one face in every frame before a correct
  retake; both mislabelled clips were removed.
- P3's second face for `two_faces` was a photo on a phone (see Findings).
- Recordings made before the recorder fix kept 8 "get ready" frames per clip;
  the parser drops them automatically where the clip clock restarts.

## Method

- **Leave one participant out.** Six rounds: tune the angle limits on five
  people, test on the sixth. Every result below is on a person the limits were
  never tuned on, and every person gets a result.
- **Tuning** searches yaw, pitch and roll limits and the iris box for the best
  balanced accuracy on "looking at the screen", separately with and without
  calibration.
- **Balanced accuracy** averages "looking" recognised and "not looking"
  recognised, so the many "away" clips do not swamp the "screen" ones. A frame
  with no gaze reading (eyes closed, no face, two faces) counts as "not looking".
- **95% confidence intervals** come from 1,000 bootstrap resamples of whole
  clips, not frames, because frames in one clip are near copies.

## Before and after

All six held-out rounds pooled.

| Setting | Looking: precision | Looking: recall | Balanced accuracy |
|---|---|---|---|
| Before: landmark proxies, #63 limits | 40.1% (18.9–59.4) | 90.2% (79.0–99.8) | 80.7% (73.5–87.9) |
| Pose angles, #63 limits | 35.1% (16.1–52.3) | 88.1% (65.2–99.8) | 77.4% (65.7–86.7) |
| After: pose, tuned limits | 48.4% (23.4–71.1) | 82.8% (59.9–99.0) | 81.3% (69.6–90.8) |
| **After: pose, tuned limits + calibration** | **49.2% (24.3–70.2)** | **83.1% (60.5–99.8)** | **81.6% (69.9–91.0)** |

Face present: precision 99.9%, recall 94.0% (87.1–99.0) in every setting.

**Per participant** (balanced accuracy):

| Held out | Before | After | After + calibration |
|---|---|---|---|
| P1 | 79.4% | 74.7% | 76.8% |
| P2 | 70.8% | 70.8% | 70.8% |
| P3 | 84.6% | 95.8% | 91.9% |
| P4 | 81.3% | 89.0% | 84.6% |
| P5 | 98.8% | 98.8% | 98.8% |
| P6 | 74.8% | 77.7% | 81.3% |

Worst participant: 70.8% (P2) in every setting.

**Where calibration helps** (held-out, tuned limits, without → with calibration):

| Case | Without | With |
|---|---|---|
| `down_notes` read as "on screen" | 32.8% | 23.6% |
| Far from the camera: "looking" recall | 2.8% | 66.7% |
| Dim light: "looking" recall | 81.7% | 60.9% |

## Thresholds chosen

| | Yaw | Pitch | Roll | Iris box (x) |
|---|---|---|---|---|
| #63 (before) | 25° | 20° | 20° | 0.20–0.80 |
| `DEFAULT_THRESHOLDS` (no calibration) | 10° | 30° | 20° | 0.20–0.80 |
| `CALIBRATED_THRESHOLDS` | 15° | 16° | 15° | 0.25–0.75 |

Both were tuned on all six participants. With calibration, five of the six
held-out rounds also chose 15° yaw and 16° pitch, so those limits do not depend
much on who is in the tuning set; without calibration, pitch moved between 16°
and 30°.

## Findings

1. **Overall gain is small and not significant.** Balanced accuracy rises from
   80.7% to 81.6%, and the intervals overlap. Six people are too few to claim
   more.
2. **The gain is where it was needed.** With calibration, the pitch limit can
   be strict (16°), so looking down at notes is caught more often, and a far
   or low camera works. Without calibration, pitch has to stay loose (30°) to
   allow for every camera height, and notes on the desk mostly pass as
   "looking".
3. **Calibration needed one fix.** A centre more than 20° off in any direction
   was refused. Sitting back from the laptop read as 23–30° upward while
   looking at the screen, so the setup that most needed calibration got none.
   Upward pitch may now reach 35°; downward stays at 20°, so a centre taken
   while looking at notes (17–20° down) is still refused. This took
   calibrated balanced accuracy from 74.1% to 79.6% on five participants.
4. **Eye-only glances are missed.** P2 looked left and right with the eyes,
   head turned under 5°; the iris stayed inside the box, so the rule read
   "looking". P2 is 70.8% in every setting.
5. **A turned head with eyes on the screen reads as "away".** The eyes can only
   veto "looking", never rescue it. No recording covers this case yet, so it
   was not measured. Combining head and eye direction is proposed in #166.
6. **A photo is accepted as a face.** A face shown on a phone was detected, and
   judged as looking at the screen. A blink check was considered and rejected:
   at 4 frames per second, no blink was seen in 7 of 27 real 10-second clips,
   so it would flag real students. On-device anti-spoofing is proposed in #165.
7. **Recorder fixes found while recording** (thanks to Joel): frames were kept
   during the countdown, and unticking consent did not stop the camera. Both
   fixed and tested.

## Limits

- Six participants, all team members of similar age, so the intervals are wide
  and the results may not hold for a class.
- No participant wore glasses, so the glasses condition is untested.
- Far distance and off-centre come from one and two participants; dim light
  from three. Participants recorded different numbers of clips (P1: 29).
- Acted, not natural: 10-second clips of a told behaviour.
- "Looking at the screen" is a camera-facing proxy, not eye tracking, and never
  a measure of attention or understanding.
- Fairness of the thresholds across people, including students with
  disabilities, is for Cyber 1 to sign off (see #166). Device, browser and
  Teams testing is Cyber 2's (#160). `VITE_LOCAL_ATTENTION_ENABLED` stays off
  until both are done.

## Recommendation

Ship the tuned limits with calibration offered at opt-in and encouraged, since
that is where the improvement is. Keep the feature flag off until Cyber 1's
fairness review and Cyber 2's device tests pass. Next: record "head turned,
eyes on the screen" and eye-only clips, and combine head and eye direction
(#166).
