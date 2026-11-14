# Held-out camera and microphone evaluation

Use people who were outside the calibration and threshold-fitting groups. Record
the release commit, browser and browser version, device class and the conditions
tested. Use assigned participant codes and obtain consent before starting.
Store exports in the study's approved private location.

1. Start the frontend with `npm run dev` from `frontend/`.
2. For camera, open `/eval/attention-recorder.html` and collect trials with and
   without glasses, typical and low lighting, off-centre and distant cameras,
   and while reading or taking notes. Keep the evaluation people separate from
   anyone whose recordings were used to select settings.
3. For microphone, open `/eval/vad-recorder.html`. Pick each room condition
   and complete both a speaking and a quiet trial. During the quiet trial with
   another speaker, the participant stays silent. Repeat on lower-spec devices.
   The recorder uses the student app's local microphone indicator and downloads
   only aggregate counts and selected condition labels.
4. Compare available readings with the instructed activity. Report unavailable
   readings separately. For microphone exports, run
   `node scripts/summarize-vad-trials.mjs /path/to/exports/*.json` from
   `frontend/` to calculate false-positive and false-negative rates by person,
   room condition and device class. Review per-person results privately before
   publishing aggregate evidence.

Adjacent samples from one trial are correlated. Report the number of people
and trials alongside the sample counts. Camera and microphone indicators do
not establish identity, attendance, understanding or grades. Link completed
evidence to #175 and #253.
