# Camera attention recordings (#159)

The recorder's CSV files go in this folder. Each row is one camera frame turned
into numbers (head angles, how open the eyes are, where the iris sits) plus the
label the person was acting out. There is no video, image or face landmark in
them, and participants appear only as codes (P1, P2, ...).

## Recording

1. From `frontend/`: `npm run dev`, then open
   http://localhost:5173/eval/attention-recorder.html in Chrome.
2. Tick the consent box, enter your participant code (P1, P2, ...; never a
   name) and start the camera. The picture stays in the browser.
3. For each set of conditions (glasses, lighting, camera position, distance),
   record one 10-second clip of every label, starting with `calibrate`. The
   page gives two seconds to get into position before each clip.
4. Download the CSV and put it here as `attention_P1.csv` (one file per person
   is easiest). Press "Delete everything recorded here" before the next person.

Aim for at least 6 people, so the held-out set (every third person) has two,
and for each person at least:

| Glasses | Lighting | Camera | Distance |
|---|---|---|---|
| as usual | normal | centred | near |
| as usual | dim | centred | near |
| as usual | normal | off-centre | near |
| as usual | normal | centred | far |

That is 4 sets of 8 clips, about 7 minutes per person. People who wear glasses
should also do the first row without them, if they can.

## Evaluating

From `frontend/`: `npm run eval:attention`. It writes
`backend/tests/eval/CV_EVALUATION.md` with the before and after numbers and
their confidence intervals, and prints the tuned thresholds to copy into
`DEFAULT_THRESHOLDS` in `frontend/src/features/attention/signals.ts`.
