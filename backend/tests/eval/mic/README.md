# Microphone voice-detection recordings (#253)

How well the classroom's microphone tells when a student is speaking. The
recorder's CSV files go in this folder; they are not committed. Each row is
one voice-detection frame (about 32 ms) turned into a single number, the
speech probability, plus the situation the person was acting out. There is no
audio in them, and participants appear only as codes (P1, P2, ...).

The recorder opens the microphone and runs the voice detector with the
classroom's own settings (`MICROPHONE_AUDIO` in `localSensors.ts`, Silero VAD
v5, threshold `SPEECH_THRESHOLD` in `signals.ts`), so the numbers are what a
student's browser would produce.

## Recording

1. From `frontend/`: `npm run prepare:attention` once, then `npm run dev`, and
   open http://localhost:5173/eval/mic-recorder.html in Chrome.
2. Tick the consent box, enter the participant code (P1, P2, ...; never a
   name, and the same code as in the camera recordings if they do both) and
   start the microphone. The live bar shows the detector reacting.
3. Set the conditions, then record one 15-second clip of every situation.
   The page gives two seconds to get ready before each clip.
4. Download the CSV and put it here as `mic_P1.csv` (one file per person is
   easiest). Press "Delete everything recorded here" before the next person.

The situations:

| Situation | The person | Should be "speaking"? |
|---|---|---|
| `speaking` | reads the passage on the page at normal volume | yes |
| `speaking_quietly` | reads it quietly, as in a library | yes |
| `speaking_over_noise` | reads it while music or a video plays | yes |
| `silent` | sits quietly | no |
| `typing` | types without speaking | no |
| `noise` | stays silent while music, a fan or other noise plays | no |
| `others_talking` | stays silent while someone else talks nearby, or a video of a person talking plays | no |

`others_talking` is expected to fail often: the detector hears a voice, not
whose voice. It is recorded so the report shows how often a student is
reported as speaking because of someone else.

For each person, at least these sets (7 clips each, about 3 minutes a set):

| Microphone | Room | Distance | Device |
|---|---|---|---|
| built in | quiet | near | usual |
| built in | quiet | far (an arm's length back) | usual |
| built in | noisy (a busy room or common area) | near | usual |

and, where possible, the first row with a headset and on a weaker laptop.
Aim for at least 6 people with a mix of voices (pitch, accent, loudness);
never record anything about a person beyond their code.

## Evaluating

From `frontend/`: `npm run eval:mic`. It cuts every clip into the
classroom's 5-second windows (a window is "speaking" if any frame in it is,
as the classroom reports it) and writes `RESULTS.md` in this folder: speech
caught and false alarms overall with 95% intervals, per situation, per
participant (with the worst one), per condition, and what other thresholds
would have done.

The CSV files are not committed (`.gitignore`), as for the camera
recordings. Whoever runs the evaluation keeps them.
