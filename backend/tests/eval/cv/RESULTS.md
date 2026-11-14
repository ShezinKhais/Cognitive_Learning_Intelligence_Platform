# Camera attention evaluation

Issues #159, #165 and #166. 18 recording file(s), 10 participant(s), 201 clips, 15428 frames.
Made with `scripts/evaluate-attention.ts`; recordings from `eval/attention-recorder.html` hold derived numbers only, no video.

## The recordings

| Label | What the person did | Clips | Frames |
|---|---|---|---|
| calibrate | Look at the middle of the screen (used only to calibrate) | 25 | 1630 |
| screen | Look at the screen and read it normally | 21 | 2177 |
| away_left | Look away, to the left of the screen | 21 | 1519 |
| away_right | Look away, to the right of the screen | 21 | 1518 |
| down_notes | Look down at notes on your desk | 21 | 1516 |
| eyes_closed | Close your eyes, facing the screen | 21 | 1519 |
| no_face | Move out of the camera view | 21 | 1522 |
| two_faces | Have a second person in view with you | 9 | 1031 |
| screen_head_turned | Keep your eyes on the screen while turning or tilting your head a little left, right, up and down | 11 | 1120 |
| away_eyes_only | Keep your head still and look to the side with your eyes only, left then right | 12 | 1158 |
| photo_on_phone | Step out of view and hold up a photo of your face on a phone | 9 | 359 |
| video_on_phone | Step out of view and hold up a video of your face playing on a phone | 9 | 359 |
| printed_photo | Step out of view and hold up a printed photo of your face | 0 | 0 |

Leave one participant out: 10 rounds, each tuning the limits on 9 participants and testing on the one left out. Every result below is on a person the limits were not tuned on, and pools all 10 rounds (183 clips).

## Before and after (held-out, all rounds pooled)

95% intervals in brackets, from 1000 bootstrap resamples of whole clips.

| Setting | Face present: precision | Face present: recall | Looking at screen: precision | Looking at screen: recall | Frames with a gaze reading | Balanced accuracy |
|---|---|---|---|---|---|---|
| Before: landmark proxies (#63) | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 49.2% (30.1%–68.1%) | 65.9% (52.7%–86.8%) | 51.5% (39.9%–64.2%) | 69.4% (60.9%–80.1%) |
| Pose angles, starting limits | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 50.3% (30.5%–69.8%) | 67.9% (42.1%–90.1%) | 51.5% (39.9%–64.2%) | 70.5% (57.5%–82.1%) |
| After: pose angles, tuned limits | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 63.4% (42.1%–79.1%) | 75.7% (59.8%–90.3%) | 51.5% (39.9%–64.2%) | 77.6% (70.2%–85.6%) |
| After + calibration | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 63.2% (41.5%–79.5%) | 71.1% (57.0%–85.2%) | 51.5% (39.9%–64.2%) | 75.8% (69.2%–82.9%) |
| #166: + combined head and eye gaze | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 68.1% (46.7%–82.2%) | 80.7% (72.4%–89.9%) | 46.6% (34.3%–60.1%) | 80.2% (76.1%–84.5%) |
| #166: + adaptive limits | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 63.6% (42.0%–79.7%) | 74.1% (58.3%–88.5%) | 51.5% (39.9%–64.2%) | 77.0% (69.5%–84.8%) |
| #166: + both | 99.6% (98.8%–100.0%) | 89.1% (77.8%–97.1%) | 68.5% (46.9%–82.4%) | 83.7% (74.5%–92.0%) | 46.8% (34.4%–60.2%) | 81.5% (76.7%–86.6%) |

Balanced accuracy counts a frame with no gaze reading as "not looking", as a five-second window with no forward frames does; it is what tuning maximises. "Two faces" gives no reading at all by design.

## Per participant

Balanced accuracy on each person, with the limits tuned on everyone else. Yaw / pitch / roll are those limits, so the spread shows how much they depend on who is in the tuning set.

| Held out | Clips | Before | After | After + calibration | + gaze | + adaptive | + both | Tuned limits (yaw / pitch / roll) | With calibration | Gaze k (yaw / pitch) |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 68 | 73.1% | 74.7% | 75.4% | 75.8% | 75.1% | 75.8% | 15° / 30° / 30° | 10° / 30° / 30° | 60 / 0 |
| P10 | 8 | 80.3% | 87.7% | 87.7% | 87.5% | 87.7% | 87.5% | 15° / 30° / 30° | 15° / 30° / 30° | 150 / 0 |
| P2 | 27 | 70.9% | 76.8% | 73.2% | 80.1% | 76.5% | 83.5% | 15° / 30° / 30° | 15° / 16° / 30° | 120 / 0 |
| P3 | 20 | 82.0% | 88.5% | 85.6% | 87.4% | 86.0% | 88.2% | 15° / 30° / 30° | 15° / 30° / 30° | 90 / 0 |
| P4 | 8 | 81.3% | 85.4% | 85.4% | 86.7% | 85.4% | 86.9% | 15° / 30° / 30° | 15° / 30° / 30° | 150 / 0 |
| P5 | 7 | 98.8% | 92.5% | 92.5% | 91.8% | 92.5% | 93.0% | 15° / 30° / 30° | 15° / 30° / 30° | 150 / 0 |
| P6 | 8 | 74.8% | 74.8% | 80.2% | 76.5% | 76.3% | 76.7% | 15° / 30° / 30° | 15° / 30° / 30° | 150 / 0 |
| P7 | 9 | 65.9% | 74.1% | 73.5% | 73.8% | 73.5% | 73.8% | 15° / 30° / 30° | 15° / 30° / 30° | 60 / 0 |
| P8 | 18 | 66.3% | 81.0% | 81.0% | 83.8% | 81.0% | 83.3% | 10° / 30° / 30° | 10° / 30° / 30° | 90 / 0 |
| P9 | 10 | 65.9% | 83.8% | 67.3% | 87.0% | 67.3% | 87.0% | 15° / 30° / 30° | 15° / 30° / 30° | 90 / 0 |

Worst participant: before 65.9% (P7), after 74.1% (P7), after + calibration 67.3% (P9), + gaze 73.8% (P7), + adaptive 67.3% (P9), + both 73.8% (P7).

## What each label was read as (After: pose angles, tuned limits)

| Label | On screen | Away | No reading |
|---|---|---|---|
| away_left | 127 (8.4%) | 949 (62.5%) | 443 (29.2%) |
| down_notes | 657 (43.3%) | 46 (3.0%) | 813 (53.6%) |
| no_face | 27 (1.8%) | 7 (0.5%) | 1488 (97.8%) |
| screen | 1776 (81.6%) | 160 (7.3%) | 241 (11.1%) |
| away_right | 122 (8.0%) | 598 (39.4%) | 798 (52.6%) |
| eyes_closed | 74 (4.9%) | 14 (0.9%) | 1431 (94.2%) |
| two_faces | 26 (2.5%) | 30 (2.9%) | 975 (94.6%) |
| screen_head_turned | 479 (42.8%) | 565 (50.4%) | 76 (6.8%) |
| away_eyes_only | 267 (23.1%) | 807 (69.7%) | 84 (7.3%) |

## By condition (After: pose angles, tuned limits, held-out, all rounds pooled)

| Condition | Value | Clips | Face present: recall | Looking: precision | Looking: recall |
|---|---|---|---|---|---|
| glasses | no | 153 | 89.6% (77.3%–98.4%) | 65.1% (41.0%–81.1%) | 75.4% (57.3%–91.0%) |
| glasses | yes | 30 | 82.9% (65.9%–96.1%) | 48.6% (20.5%–79.5%) | 78.9% (65.8%–91.1%) |
| lighting | normal | 106 | 94.4% (89.3%–98.1%) | 63.0% (36.6%–79.4%) | 89.2% (75.0%–95.9%) |
| lighting | dim | 77 | 86.6% (70.2%–98.1%) | 63.7% (26.6%–87.4%) | 67.5% (47.3%–88.3%) |
| position | centred | 159 | 87.6% (75.2%–97.2%) | 58.1% (36.2%–76.5%) | 72.1% (55.3%–91.2%) |
| position | off_centre | 24 | 99.2% (96.4%–100.0%) | 84.0% (8.8%–97.0%) | 87.2% (39.2%–100.0%) |
| distance | near | 155 | 88.1% (73.9%–98.3%) | 63.1% (37.5%–80.5%) | 87.1% (77.9%–92.3%) |
| distance | far | 28 | 92.8% (76.4%–98.0%) | 65.2% (16.3%–88.6%) | 47.3% (41.4%–87.5%) |

## What each label was read as (After + calibration)

| Label | On screen | Away | No reading |
|---|---|---|---|
| away_left | 107 (7.0%) | 969 (63.8%) | 443 (29.2%) |
| down_notes | 654 (43.1%) | 49 (3.2%) | 813 (53.6%) |
| no_face | 24 (1.6%) | 10 (0.7%) | 1488 (97.8%) |
| screen | 1697 (78.0%) | 239 (11.0%) | 241 (11.1%) |
| away_right | 107 (7.0%) | 613 (40.4%) | 798 (52.6%) |
| eyes_closed | 65 (4.3%) | 23 (1.5%) | 1431 (94.2%) |
| two_faces | 21 (2.0%) | 35 (3.4%) | 975 (94.6%) |
| screen_head_turned | 422 (37.7%) | 622 (55.5%) | 76 (6.8%) |
| away_eyes_only | 255 (22.0%) | 819 (70.7%) | 84 (7.3%) |

## By condition (After + calibration, held-out, all rounds pooled)

| Condition | Value | Clips | Face present: recall | Looking: precision | Looking: recall |
|---|---|---|---|---|---|
| glasses | no | 153 | 89.6% (77.3%–98.4%) | 65.2% (41.0%–81.6%) | 71.6% (56.1%–86.5%) |
| glasses | yes | 30 | 82.9% (65.9%–96.1%) | 45.3% (16.8%–78.1%) | 65.2% (37.9%–88.5%) |
| lighting | normal | 106 | 94.4% (89.3%–98.1%) | 60.9% (35.1%–77.4%) | 79.1% (65.9%–91.0%) |
| lighting | dim | 77 | 86.6% (70.2%–98.1%) | 65.0% (26.7%–88.7%) | 66.3% (46.8%–86.0%) |
| position | centred | 159 | 87.6% (75.2%–97.2%) | 56.8% (34.6%–75.7%) | 66.2% (52.1%–83.5%) |
| position | off_centre | 24 | 99.2% (96.4%–100.0%) | 88.0% (18.1%–98.4%) | 86.9% (51.0%–100.0%) |
| distance | near | 155 | 88.1% (73.9%–98.3%) | 62.7% (37.8%–80.8%) | 81.1% (70.8%–87.3%) |
| distance | far | 28 | 92.8% (76.4%–98.0%) | 65.6% (14.0%–89.3%) | 46.3% (39.2%–87.4%) |

## #166 labels on their own (held-out, all rounds pooled)

Share of frames read as "on screen". `screen_head_turned` should be high, `away_eyes_only` low.

| Label | Clips | After + calibration | #166: + combined head and eye gaze | #166: + adaptive limits | #166: + both |
|---|---|---|---|---|---|
| screen_head_turned | 11 | 37.7% (28.9%–42.7%) | 58.4% (41.6%–66.4%) | 38.0% (29.8%–43.4%) | 58.4% (41.1%–66.6%) |
| away_eyes_only | 12 | 22.0% (13.2%–55.9%) | 20.0% (11.1%–53.1%) | 21.9% (12.9%–56.1%) | 19.9% (11.0%–53.1%) |

## Adaptation fairness check

Of 13080 held-out frames, adaptation turned 19 from "on screen" to "away" (only a moved centre can do this; the learned limits are never stricter) and 0 from "away" to "no reading" (a normal wider than the camera can measure).

Adaptation settings replayed: `{"rate":0.05,"maxCentreStepDegrees":0.5,"spreadMultiplier":3,"maxLimits":{"yaw":25,"pitch":30,"roll":25},"minFrames":12}` (suggested; `ADAPTATION` is off in `signals.ts`). The recordings' only certain "looking" moments are the calibrate clips, so adaptation learns from those; the classroom also learns while a student types an answer, which these clips do not contain.

## Anti-spoofing (#165)

Held out one participant at a time (6 rounds). Acceptance bar to agree: under 2.0% of live faces rejected, in every condition. Only frames with exactly one face count.

| Setting | Spoofs caught | Live faces wrongly rejected | Live clips with any rejection |
|---|---|---|---|
| Suggested `{"everyMs":2000,"window":3,"spoofBelow":0.2}` | 19.6% (9.2%–31.1%) | 0.0% (0.0%–0.0%) | 0.0% |
| Tuned without the held-out person | 56.2% (40.3%–71.3%) | 0.1% (0.0%–0.4%) | 1.3% |

**Per participant** (tuned without them):

| Held out | Settings | Spoofs caught | Live faces wrongly rejected |
|---|---|---|---|
| P1 | `{"everyMs":1000,"window":2,"spoofBelow":0.5}` | 48.4% | 0.0% |
| P10 | `{"everyMs":1000,"window":2,"spoofBelow":0.5}` | 77.2% | 0.0% |
| P3 | `{"everyMs":1000,"window":2,"spoofBelow":0.5}` | 75.0% | 1.3% |
| P7 | `{"everyMs":1000,"window":2,"spoofBelow":0.5}` | 0.0% | 0.0% |
| P8 | `{"everyMs":1000,"window":2,"spoofBelow":0.5}` | 63.9% | 0.0% |
| P9 | `{"everyMs":1000,"window":2,"spoofBelow":0.5}` | 74.4% | 0.0% |

**By condition** (tuned without the held-out person):

| Condition | Value | Spoofs caught | Live faces wrongly rejected |
|---|---|---|---|
| glasses | no | 47.8% (27.8%–66.6%) | 0.1% (0.0%–0.6%) |
| glasses | yes | 72.1% (50.6%–89.0%) | 0.0% (0.0%–0.0%) |
| lighting | normal | 55.6% (32.6%–78.8%) | 0.0% (0.0%–0.0%) |
| lighting | dim | 57.0% (36.7%–75.1%) | 0.2% (0.0%–0.7%) |
| position | centred | 54.0% (37.9%–69.2%) | 0.1% (0.0%–0.5%) |
| position | off_centre | 76.1% (59.4%–91.4%) | 0.0% (0.0%–0.0%) |
| distance | near | 57.8% (41.2%–72.5%) | 0.1% (0.0%–0.5%) |
| distance | far | 49.2% (0.0%–89.5%) | 0.0% (0.0%–0.0%) |

**By spoof type** (caught, tuned without the held-out person):

- photo_on_phone: 61.9% (39.5%–80.2%) of 331 frames
- video_on_phone: 50.3% (31.6%–70.6%) of 318 frames

Time per check in the browser: median 7.0 ms, 95th percentile 9.0 ms (4381 checks). Note the device each participant used: a slow laptop is the case that matters.

Tuned on every recording: `{"everyMs":1000,"window":2,"spoofBelow":0.5}` (meets the bar there: 56.2% caught, 0.1% live rejected). Shipped `LIVENESS`: off.

## Thresholds

- Starting limits (#63): `maxYawDegrees: 25, maxPitchDegrees: 20, maxRollDegrees: 20, irisX: [0.2, 0.8]`
- Tuned on every recording, without calibration: `maxYawDegrees: 15, maxPitchDegrees: 30, maxRollDegrees: 30, irisX: [0.3, 0.7]` (balanced accuracy on those recordings 78.5%)
- Tuned on every recording, with calibration: `maxYawDegrees: 15, maxPitchDegrees: 30, maxRollDegrees: 30, irisX: [0.3, 0.7]` (78.1%)
- #166 gaze model tuned on every recording: `kYaw: 150, kPitch: 0`, gaze limits `maxYawDegrees: 20, maxPitchDegrees: 25, maxRollDegrees: 30, irisX: [0.3, 0.7]` (82.4%). Shipped `GAZE_MODEL`: off.

These are the limits to ship. The held-out results above estimate how they do on a new person, since each round tuned the same way without that person.

- Shipped in `signals.ts`: `DEFAULT_THRESHOLDS` maxYawDegrees: 10, maxPitchDegrees: 30, maxRollDegrees: 20, irisX: [0.2, 0.8]; `CALIBRATED_THRESHOLDS` maxYawDegrees: 15, maxPitchDegrees: 16, maxRollDegrees: 15, irisX: [0.25, 0.75].

If the tuned values above differ from the shipped ones, copy them into `signals.ts` and the threshold test in `tests/attention.test.ts`.

## Limits

- 10 participants: a small sample, so the intervals are wide and the numbers may not hold for a whole class.
- Acted, not natural: people were told what to do for 10 seconds at a time.
- "Looking at the screen" is a camera-facing proxy, not eye tracking, and never a measure of attention or understanding.
- Fairness of the tuned thresholds across people is for Cyber 1 to sign off; devices and Teams are tested by Cyber 2.
