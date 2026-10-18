# Camera attention evaluation

Issue #159. 7 recording file(s), 6 participant(s), 70 clips, 2801 frames.
Made with `scripts/evaluate-attention.ts`; recordings from `eval/attention-recorder.html` hold derived numbers only, no video.

## The recordings

| Label | What the person did | Clips | Frames |
|---|---|---|---|
| calibrate | Look at the middle of the screen (used only to calibrate) | 12 | 480 |
| screen | Look at the screen and read it normally | 9 | 359 |
| away_left | Look away, to the left of the screen | 9 | 359 |
| away_right | Look away, to the right of the screen | 9 | 360 |
| down_notes | Look down at notes on your desk | 9 | 360 |
| eyes_closed | Close your eyes, facing the screen | 9 | 361 |
| no_face | Move out of the camera view | 9 | 362 |
| two_faces | Have a second person in view with you | 4 | 160 |

Leave one participant out: 6 rounds, each tuning the limits on 5 participants and testing on the one left out. Every result below is on a person the limits were not tuned on, and pools all 6 rounds (70 clips).

## Before and after (held-out, all rounds pooled)

95% intervals in brackets, from 1000 bootstrap resamples of whole clips.

| Setting | Face present: precision | Face present: recall | Looking at screen: precision | Looking at screen: recall | Frames with a gaze reading | Balanced accuracy |
|---|---|---|---|---|---|---|
| Before: landmark proxies (#63) | 99.9% (99.6%–100.0%) | 94.0% (87.1%–99.0%) | 40.1% (18.9%–59.4%) | 90.2% (79.0%–99.8%) | 52.0% (40.9%–63.0%) | 80.7% (73.5%–87.9%) |
| Pose angles, starting limits | 99.9% (99.6%–100.0%) | 94.0% (87.1%–99.0%) | 35.1% (16.1%–52.3%) | 88.1% (65.2%–99.8%) | 52.0% (40.9%–63.0%) | 77.4% (65.7%–86.7%) |
| After: pose angles, tuned limits | 99.9% (99.6%–100.0%) | 94.0% (87.1%–99.0%) | 48.4% (23.4%–71.1%) | 82.8% (59.9%–99.0%) | 52.0% (40.9%–63.0%) | 81.3% (69.6%–90.8%) |
| After + calibration | 99.9% (99.6%–100.0%) | 94.0% (87.1%–99.0%) | 49.2% (24.3%–70.2%) | 83.1% (60.5%–99.8%) | 52.0% (40.9%–63.0%) | 81.6% (69.9%–91.0%) |

Balanced accuracy counts a frame with no gaze reading as "not looking", as a five-second window with no forward frames does; it is what tuning maximises. "Two faces" gives no reading at all by design.

## Per participant

Balanced accuracy on each person, with the limits tuned on everyone else. Yaw / pitch / roll are those limits, so the spread shows how much they depend on who is in the tuning set.

| Held out | Clips | Before | After | After + calibration | Tuned limits (yaw / pitch / roll) | With calibration |
|---|---|---|---|---|---|---|
| P1 | 29 | 79.4% | 74.7% | 76.8% | 10° / 16° / 15° | 10° / 12° / 15° |
| P2 | 7 | 70.8% | 70.8% | 70.8% | 10° / 30° / 20° | 15° / 16° / 15° |
| P3 | 11 | 84.6% | 95.8% | 91.9% | 10° / 30° / 20° | 15° / 16° / 20° |
| P4 | 8 | 81.3% | 89.0% | 84.6% | 10° / 30° / 20° | 15° / 16° / 15° |
| P5 | 7 | 98.8% | 98.8% | 98.8% | 10° / 30° / 20° | 15° / 16° / 15° |
| P6 | 8 | 74.8% | 77.7% | 81.3% | 15° / 30° / 20° | 15° / 16° / 15° |

Worst participant: before 70.8% (P2), after 70.8% (P2), after + calibration 70.8% (P2).

## What each label was read as (After: pose angles, tuned limits)

| Label | On screen | Away | No reading |
|---|---|---|---|
| away_left | 91 (25.3%) | 247 (68.8%) | 21 (5.8%) |
| down_notes | 118 (32.8%) | 56 (15.6%) | 186 (51.7%) |
| no_face | 0 (0.0%) | 1 (0.3%) | 361 (99.7%) |
| screen | 279 (77.7%) | 58 (16.2%) | 22 (6.1%) |
| away_right | 62 (17.2%) | 266 (73.9%) | 32 (8.9%) |
| eyes_closed | 18 (5.0%) | 3 (0.8%) | 340 (94.2%) |
| two_faces | 8 (5.0%) | 1 (0.6%) | 151 (94.4%) |

## By condition (After: pose angles, tuned limits, held-out, all rounds pooled)

| Condition | Value | Clips | Face present: recall | Looking: precision | Looking: recall |
|---|---|---|---|---|---|
| glasses | no | 70 | 94.0% (87.1%–99.0%) | 48.4% (23.4%–71.1%) | 82.8% (59.9%–99.0%) |
| lighting | normal | 48 | 95.0% (87.0%–99.8%) | 44.4% (17.1%–69.0%) | 83.3% (45.6%–100.0%) |
| lighting | dim | 22 | 92.1% (79.0%–99.8%) | 59.1% (0.0%–90.9%) | 81.7% (61.1%–97.5%) |
| position | centred | 55 | 93.1% (85.2%–99.7%) | 47.6% (18.4%–74.0%) | 80.8% (52.6%–100.0%) |
| position | off_centre | 15 | 97.3% (92.4%–100.0%) | 51.1% (0.0%–87.6%) | 89.5% (84.6%–94.6%) |
| distance | near | 63 | 96.9% (91.9%–99.8%) | 51.5% (25.3%–74.3%) | 92.4% (82.1%–99.5%) |
| distance | far | 7 | 70.9% (34.7%–96.0%) | 2.8% (0.0%–100.0%) | 2.8% (2.8%–2.8%) |

## What each label was read as (After + calibration)

| Label | On screen | Away | No reading |
|---|---|---|---|
| away_left | 89 (24.8%) | 249 (69.4%) | 21 (5.8%) |
| down_notes | 85 (23.6%) | 89 (24.7%) | 186 (51.7%) |
| no_face | 0 (0.0%) | 1 (0.3%) | 361 (99.7%) |
| screen | 280 (78.0%) | 57 (15.9%) | 22 (6.1%) |
| away_right | 98 (27.2%) | 230 (63.9%) | 32 (8.9%) |
| eyes_closed | 15 (4.2%) | 6 (1.7%) | 340 (94.2%) |
| two_faces | 2 (1.3%) | 7 (4.4%) | 151 (94.4%) |

## By condition (After + calibration, held-out, all rounds pooled)

| Condition | Value | Clips | Face present: recall | Looking: precision | Looking: recall |
|---|---|---|---|---|---|
| glasses | no | 70 | 94.0% (87.1%–99.0%) | 49.2% (24.3%–70.2%) | 83.1% (60.5%–99.8%) |
| lighting | normal | 48 | 95.0% (87.0%–99.8%) | 45.4% (18.6%–68.6%) | 94.6% (81.6%–100.0%) |
| lighting | dim | 22 | 92.1% (79.0%–99.8%) | 66.0% (0.0%–95.3%) | 60.9% (0.0%–97.5%) |
| position | centred | 55 | 93.1% (85.2%–99.7%) | 45.6% (15.6%–71.9%) | 81.2% (50.2%–100.0%) |
| position | off_centre | 15 | 97.3% (92.4%–100.0%) | 65.4% (0.0%–94.7%) | 89.5% (79.5%–100.0%) |
| distance | near | 63 | 96.9% (91.9%–99.8%) | 48.3% (22.5%–71.3%) | 85.0% (59.3%–100.0%) |
| distance | far | 7 | 70.9% (34.7%–96.0%) | 61.5% (0.0%–100.0%) | 66.7% (66.7%–66.7%) |

## Thresholds

- Starting limits (#63): `maxYawDegrees: 25, maxPitchDegrees: 20, maxRollDegrees: 20, irisX: [0.2, 0.8]`
- Tuned on every recording, without calibration: `maxYawDegrees: 10, maxPitchDegrees: 30, maxRollDegrees: 20, irisX: [0.2, 0.8]` (balanced accuracy on those recordings 83.5%)
- Tuned on every recording, with calibration: `maxYawDegrees: 15, maxPitchDegrees: 16, maxRollDegrees: 15, irisX: [0.25, 0.75]` (86.1%)

These are the limits to ship. The held-out results above estimate how they do on a new person, since each round tuned the same way without that person.

- Shipped in `signals.ts`: `DEFAULT_THRESHOLDS` maxYawDegrees: 10, maxPitchDegrees: 30, maxRollDegrees: 20, irisX: [0.2, 0.8]; `CALIBRATED_THRESHOLDS` maxYawDegrees: 15, maxPitchDegrees: 16, maxRollDegrees: 15, irisX: [0.25, 0.75].

If the tuned values above differ from the shipped ones, copy them into `signals.ts` and the threshold test in `tests/attention.test.ts`.

## Limits

- 6 participants, all team members: a small sample of similar people, so the intervals are wide and the numbers may not hold for a whole class.
- Acted, not natural: people were told what to do for 10 seconds at a time.
- "Looking at the screen" is a camera-facing proxy, not eye tracking, and never a measure of attention or understanding.
- Fairness of the tuned thresholds across people is for Cyber 1 to sign off; devices and Teams are tested by Cyber 2.
