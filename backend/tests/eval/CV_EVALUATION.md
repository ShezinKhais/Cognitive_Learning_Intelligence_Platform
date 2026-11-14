# Camera attention evaluation (Phase 8, AI 1, #159)

How well the browser's camera indicator tells whether a student is looking at
the screen, measured on six team members (#159), then on ten participants
including four volunteers (second round, #253), before and after tuning. Every
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
  calibration. With calibration on, a person whose calibration is missing or
  refused is judged with the uncalibrated limits, as the app does; every set
  in these recordings had a usable calibration, so no number depends on it.
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
   so it would flag real students. On-device anti-spoofing is now built, off
   until recorded: see the #165 section below.
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

## Second round: ten participants (#253, #165, #166)

**Recorded November 2026.** The six team members (P1–P6, the #159 clips plus
P1–P3's later #166 clips) and four new volunteers (P7–P10), each on their own
laptop through the recorder, coded by number only. 201 clips, 15,428 frames.
New conditions: glasses (P1, P9), dim light (P1, P8), far (P7, P9),
off-centre (P8), 3-minute natural clips (P2, P8), and photo and video spoofs
from six people. Cleaning, by hand: duplicate downloads dropped (three P1
files were exact copies of others), retakes and mistaken clips removed on the
participant's word, `two_faces` clips with no second face in any frame
removed, and one 3-minute `no_face` clip cut to 10 seconds. Full tables:
[`cv/RESULTS.md`](cv/RESULTS.md).

**Gaze, leaving one participant out** (balanced accuracy, 95% interval):

| Setting | All | Worst participant |
|---|---|---|
| Before (#63 landmark proxies) | 69.4% (60.9–80.1) | 65.9% |
| Pose angles, tuned limits | 77.6% (70.2–85.6) | 74.1% |
| Tuned limits + calibration | 75.8% (69.2–82.9) | 67.3% |
| #166: + combined head and eye gaze | 80.2% (76.1–84.5) | 73.8% |
| **#166: + both (combined gaze and adaptation)** | **81.5% (76.7–86.6)** | 73.8% |

- **#166 helps.** "Eyes on the screen, head turned" read as on screen 58%
  of the time with the combined gaze, against 38%; eye-only glances stay
  mostly "away" (20% on screen). Adaptation adds little on its own.
- **Adaptation is not quite never harsher:** 19 of 13,080 held-out frames
  (0.15%) went from "on screen" to "away", all through a moved centre. Small,
  but for Cyber 1 to judge.
- **Calibration no longer helps** on this set (75.8% against 77.6%).
- **Weak spots:** looking down at notes reads as on screen 43% of the time;
  with glasses a face is found 83% of the time (90% without) and "looking" is
  right 49% of the time; sitting far back, real looking is caught 47% of the
  time; turning away right often gives no face at all with glasses.
- **Tuned limits differ from #159's** (yaw 15° against 10°;
  calibrated pitch 30° against 16°). PR #298 ships the tuned limits (see the
  decisions below).

**Anti-spoofing (#165), leaving one participant out** (six people with spoof
clips, tuned settings `everyMs 1000, window 2, spoofBelow 0.5`):

| | Result |
|---|---|
| Live faces wrongly rejected | **0.1%** (0.0–0.4); worst participant 1.3% (P3); every condition under 0.2% |
| Spoofs caught | **56%** (40–71): photos 62%, videos 50%; none of P7's |
| Time per check | 7 ms median, 9 ms 95th percentile |

It meets the agreed bar of under 2% live faces rejected, but misses about
half the photos and videos, and printed photos were not tested.

**Limits of this round:** ten people, four of them new; acted 10-second clips
apart from two long ones; no printed photos and no weaker laptop; P1 has the
most clips (68). "Looking at the screen" stays a camera-facing proxy, never
a measure of attention or understanding.

**Measured without calibration** (same leave-one-participant-out method; adaptation learns from the
calibrate clips as a stand-in for the moments the classroom learns from while a student types):

| Setting | All | Worst participant |
|---|---|---|
| #166 combined gaze + adaptation, with calibration | 81.5% (76.7–86.6) | 73.8% (P7) |
| **#166 combined gaze + adaptation, without calibration** | **81.4% (76.0–87.7)** | **76.9% (P6)** |
| #166 combined gaze, without calibration | 80.2% (75.2–85.4) | |

The same overall, and the worst-off participant does better (P7: 73.8% to
82.2%). `screen_head_turned` reads 57.6% on screen, `away_eyes_only` 21.3%.

**Decided by AI 1 (Luna), November 2026, and switched on in PR #298:**
- `LIVENESS` on, with the tuned settings `everyMs 1000, window 2, spoofBelow 0.5` (#165).
- `GAZE_MODEL` on, fitted without calibration (`kYaw 120, kPitch 0`), and
  `ADAPTATION` on with the suggested settings (#166).
- **Calibration dropped** from the student's camera panel. Every student is
  judged with `DEFAULT_THRESHOLDS`, the gaze limits tuned without calibration:
  yaw 15° / pitch 25° / roll 30°, iris 0.3–0.7.
- **What a rejected face does** (G34, anti-spoofing without proctoring): a face
  judged not live counts as no face, with no gaze reading (`applyLiveness`), on
  the student's device only. It reaches the server like any moment with no face
  in view, inside the usual derived figures. Nothing marks it as a suspected
  photo or video: no flag, alert or message goes to the lecturer, and nothing
  is stored about it.

**Still needed before merging:** Cyber 1 (Hunain) fairness sign-off on
`LIVENESS` and `ADAPTATION`, as #165 and #166 require, and a spoof check added
to Cyber 2's device checklist (#160).

## Next: adaptive limits and combined gaze (#166)

**Status: measured on ten participants and switched on in PR #298** (see the
second round above). `GAZE_MODEL` and `ADAPTATION` in `signals.ts` now hold the
settings fitted there; setting either back to `null` returns the browser to
#159's rule. The plan below is kept as the record of how it was built.

| Part | File | What it does |
|---|---|---|
| Combined gaze | `signals.ts` (`GazeModel`, `gazeAngles`) | gaze yaw = head yaw + k × (iris x − the student's iris x), and the same for pitch. The eyes can rescue a turned head as well as veto a still one. |
| Head tilt | `signals.ts` (`GazeModel.maxRollDegrees`) | With the combined gaze, tilting the head (ear towards shoulder) is ignored up to 45°, then gives no reading. A tilt hardly moves where the eyes point; with the #159 rule, P2's `screen_head_turned` clip (head tilted about 30°, eyes on the screen) read 3% "looking", 93% with the change. |
| Eyes that disagree | `signals.ts` (`gazeAngles`, `Calibration.eyeGapX`) | If the two irises disagree by more than 0.15 beyond the student's own calibrated gap, there is no reading, never "away". A squint present while calibrating is the student's normal. |
| Adaptive limits | `signals.ts` (`learn`, `adaptedThresholds`, `classifyAdaptive`) | Learns the student's centre and spread from good moments; limits = 3 × their spread, never below the standard limits, never above 25° / 30° / 25°. A wider normal than that gives "no reading". |
| Good moments | `face.worker.ts`, `localSensors.ts` (`markLookingAtScreen`), `StudentLiveSessionPage.tsx` | The calibration, and 1.5 s after each key typed in a checkpoint answer. Frames far from the current normal are skipped, so a glance at the keyboard or a long look away is not learned. |
| Drift | `learn` | The centre moves at most 0.5° per frame and stays inside the range a calibration may have. |
| Recorder | `eval/evaluation.ts`, `eval/recorder.ts` | New labels `screen_head_turned`, `away_eyes_only`; clips of 10 s, 1 min or 3 min. |
| Evaluation | `evaluation.ts` (`tuneGaze`, `observe`), `scripts/evaluate-attention.ts` | Fits k per axis leaving one participant out; replays adaptation learning from the calibrate clips; rows "+ gaze", "+ adaptive", "+ both" per participant, per label and per condition, with intervals; the worst participant; the new labels on their own; a count of frames adaptation made stricter. |
| Tests | `tests/attention.test.ts` | Learned limits never stricter (random runs), rescue and veto, eyes that disagree, drift, no reading beyond the cap, tuning k. |

**Fairness rules kept:** adaptation never guesses why a student's normal is
what it is and works the same for everyone; learned limits are never stricter
than the standard ones; "no reading" instead of "away" when the camera cannot
measure someone's normal; recorded accommodations still switch camera scoring
off on the server (`engagement.py`); nothing new leaves the browser and the
`signal.attention` payload is unchanged. The camera panel now says plainly that
leaving the camera off never counts against the student (the server marks
camera signals "unavailable", not negative).

**One way adaptation can still read a frame as "away" that #159 read as
"on screen":** a moved centre (the limits themselves only widen). The report
counts these frames, so the cost is visible.

**To decide with Cyber 1:**
- `engagement_baseline.py` already reads the server-side *score* against the
  student's own session. If both are on, a fidgety student is helped twice
  (wider per-frame limits, then a lower personal baseline). Compare the two on
  the long clips before switching `ADAPTATION` on.
- `student.attention_threshold` is still unused. Seeding the browser's limits
  from it would mean sending per-student settings to the browser; the
  suggestion is to remove it, since adaptation learns the same thing locally.

**To finish #166:** record the labels in `cv/README.md`, run
`npm run eval:attention`, and copy the before and after tables here. Switch on
`GAZE_MODEL` (with the fitted k) and `ADAPTATION` only if the worst participant
improves and the existing labels do not get worse.

## Next: anti-spoofing (#165)

**Status: measured on six participants' spoof clips and switched on in PR #298**
(see the second round above). `LIVENESS` in
`frontend/src/features/attention/liveness.ts` holds the tuned settings; setting
it back to `null` turns the check off, and the model is then not even
downloaded in the classroom.

**What a rejection does, and does not do (G34: anti-spoofing without
proctoring).** A rejected face only changes the student's own signal in the
browser: `face_present: false` and no gaze reading, exactly as if nobody were
in view. Nothing about spoofing is sent, stored, or shown to the lecturer or
the student; the server has no spoof field and cannot tell a rejected face
from an empty chair.

**The problem.** A photo or video of a face on a phone is detected as a face,
and as "looking at the screen" (Findings, point 6). A blink rule was rejected
because, at 4 frames per second, real students would be flagged.

**The fix.** A small open model that is trained to tell a live face from one
on a screen or printed paper, run in the browser on the face crop MediaPipe
already finds.

| Part | File | What it does |
|---|---|---|
| Model | `frontend/attention-models/minifasnet_v2_80x80.onnx` | MiniFASNetV2 from Minivision's Silent-Face-Anti-Spoofing (Apache-2.0), 1.7 MB, 80 x 80 input, about 0.4 M parameters. Converted from the published weights by `convert_minifasnet.py` next to it; committed and pinned by SHA-256 in `scripts/prepare-attention.mjs`, so nothing is fetched at build or run time. |
| Crop and input | `liveness.ts` (`faceBox`, `cropBox`, `MODEL_INPUT`) | The face box from the landmarks, grown 2.7 times as the model was trained (a port of the source's `_get_new_box`, checked against it on 2,000 random boxes), resized to 80 x 80 by the browser, then turned into blue-green-red, 0 to 255, by ONNX Runtime itself, so app code never handles pixels (the privacy test forbids `getImageData` in `src/`). |
| Runtime | `livenessModel.ts` | `onnxruntime-web` (already shipped for the microphone), one thread, engine files from `public/attention/onnx/`. Loaded only when needed. |
| Vote | `liveness.ts` (`noteFrame`, `recordCheck`, `isSpoof`) | One check every `everyMs`, not every frame. A face is rejected only when **every one** of the last `window` checks says "not live". A face leaving, a second face, or a gap in frames starts the vote again. A failed check never counts towards rejecting. |
| Effect | `applyLiveness`, `face.worker.ts` | A rejected face is reported as no face: `face_present: false`, no gaze reading. Nothing is learned from it by adaptation (#166). The payload is unchanged. |
| Calibration | `liveness.ts` (`forCalibration`), `face.worker.ts` | Frames of a face already judged not live are left out of calibration, and so out of the adaptation it seeds (#166). Limit: the vote needs a full window (about 4 s at the suggested settings), so a photo first shown during the 3-second calibration is not yet rejected. |
| Fails safe | `face.worker.ts` | If the model cannot load, faces are judged exactly as before. |
| Recorder | `eval/evaluation.ts`, `eval/recorder.ts` | New labels `photo_on_phone`, `video_on_phone`, `printed_photo`; a `live` score and `live_ms` time per frame in the CSV. Older files still parse. |
| Evaluation | `evaluation.ts` (`replayLiveness`, `livenessCounts`, `tuneLiveness`), `scripts/evaluate-attention.ts` | Replays the browser's vote on the recordings. Leaving one participant out: spoofs caught and live faces wrongly rejected, with clip bootstrap intervals, per participant, per condition, per spoof type, and time per check. Spoof clips are kept out of the #159 and #166 tables so those stay comparable. |
| Tests | `frontend/tests/liveness.test.ts` | The vote, resets, failed checks, crop and input maths, CSV round trip, tuning, the model's checksum, and that the model loads and answers. |

**Tuning rule.** Wrongly rejecting a real student is worse than missing a
photo (#165), so `tuneLiveness` first keeps only settings that reject under 2%
of live faces on the tuning set, then picks the one that catches the most
spoofs. If none get under 2%, it picks the one rejecting the fewest live
faces, and the report says the bar was not met.

**Checked so far, without recordings:**
- The ONNX file gives the same answers as the original PyTorch model (to
  0.0001) and loads in Chromium from our own server.
- The crop matches the original code exactly on 2,000 random face boxes.
- The vote, resets and tuning behave as described (unit tests).

**Known differences from how the model was trained**, to watch in the numbers:
- The original found faces with RetinaFace; here the box comes from MediaPipe's
  landmarks, which cut off closer to the hairline. The 2.7 times crop includes
  much more than the face either way, but a tighter box means a slightly
  smaller crop.
- The classroom camera is 320 x 240, so the crop is often upscaled to 80 x 80.
  Low resolution hides the moiré and glare the model looks for, and may hurt
  both rates.

**To finish #165:** record the labels in `cv/README.md`, run
`npm run eval:attention`, and copy the anti-spoofing tables here. Switch
`LIVENESS` on (with the tuned settings) only if live faces wrongly rejected are
under the agreed bar for **every** participant and condition, and Cyber 1 has
signed off fairness across skin tones, lighting and cameras. Add a spoof check
to Cyber 2's device checklist (#160) at the same time.
