# Microphone voice detection

5 participants, 51 clips, 153 windows of 5 seconds, at the classroom's threshold of 0.6. A window counts as "speaking" if any frame in it does, as in the classroom. 95% intervals resample whole clips.

## Overall

| | Windows | No reading | Speech caught | False alarms (silent but "speaking") | Balanced accuracy |
|---|---|---|---|---|---|
| All | 153 | 0 | 61 of 69 · 88% (75% to 99%) | 28 of 84 · 33% (17% to 51%) | 78% (67% to 88%) |

Worst participant: P9, balanced accuracy 53%.

## By situation

| Situation | Person speaking? | Windows reported "speaking" |
|---|---|---|
| speaking | yes | 27 of 27 |
| speaking_quietly | yes | 14 of 21 |
| speaking_over_noise | yes | 20 of 21 |
| silent | no | 0 of 21 |
| typing | no | 0 of 21 |
| noise | no | 10 of 21 |
| others_talking | no | 18 of 21 |

## By participant

| | Windows | No reading | Speech caught | False alarms (silent but "speaking") | Balanced accuracy |
|---|---|---|---|---|---|
| P1 | 42 | 0 | 17 of 18 · 94% | 6 of 24 · 25% | 85% |
| P10 | 21 | 0 | 6 of 9 · 67% | 4 of 12 · 33% | 67% |
| P7 | 27 | 0 | 15 of 15 · 100% | 4 of 12 · 33% | 83% |
| P8 | 42 | 0 | 18 of 18 · 100% | 8 of 24 · 33% | 83% |
| P9 | 21 | 0 | 5 of 9 · 56% | 6 of 12 · 50% | 53% |

## By condition

| | Windows | No reading | Speech caught | False alarms (silent but "speaking") | Balanced accuracy |
|---|---|---|---|---|---|
| microphone: built_in | 111 | 0 | 44 of 51 · 86% | 22 of 60 · 37% | 75% |
| microphone: headset | 42 | 0 | 17 of 18 · 94% | 6 of 24 · 25% | 85% |
| room: noisy | 24 | 0 | 12 of 12 · 100% | 4 of 12 · 33% | 83% |
| room: quiet | 129 | 0 | 49 of 57 · 86% | 24 of 72 · 33% | 76% |
| distance: far | 87 | 0 | 35 of 39 · 90% | 18 of 48 · 38% | 76% |
| distance: near | 66 | 0 | 26 of 30 · 87% | 10 of 36 · 28% | 79% |
| device: usual | 153 | 0 | 61 of 69 · 88% | 28 of 84 · 33% | 78% |

## Other thresholds

For information only: choosing a threshold from this table and reporting it on the same recordings would overstate it.

| Threshold | Speech caught | False alarms |
|---|---|---|
| 0.5 | 90% | 35% |
| 0.6 (classroom) | 88% | 33% |
| 0.7 | 88% | 31% |
| 0.8 | 87% | 30% |
| 0.9 | 83% | 25% |
