# Live lecturer speech → chatbot catch-up

PR #181 supports three sources: reviewed notes written during class, optional
post-meeting Teams transcript drafts, and automatic live transcription from the
**lecturer's microphone**. This is the microphone-based design Joel selected.
It does not obtain all participants' audio from Teams or poll Graph for a live
transcript. Microsoft Graph's existing post-meeting import is unchanged.

## Teaching workflow

1. Start the class and open **Discussion minutes** from the lecturer's live page.
2. Keep that page in a **separate visible window** while presenting. Enable the
   explicit notice/consent/automatic-sharing checkbox, then click **Start live
   transcription** and grant the browser microphone permission.
3. The browser collects mono 16 kHz PCM in memory and sends 10-second WAV chunks
   through a dedicated, authenticated staff endpoint. An offline local Whisper
   model on the C.L.I.P server recognizes speech. No recording file is created.
4. Recognized text becomes a timestamped **Automatic live transcript — unreviewed**
   entry automatically. Students see new entries within the 5-second refresh
   interval; every discussion-chat question retrieves the current database
   record, so it can answer about new speech as it becomes available. No manual
   note publication is needed for the automatic feed.
5. Students ask in **Catch up on this session**, including a selected 10/30-minute
   window. Replies cite timestamps and link to the full segment. The existing
   tutor guardrails, checkpoint restrictions, request limits and cancellation
   still apply. Ordinary slide-based chat remains a separate source.
6. The lecturer can edit a segment through the existing publishing form and
   affirm sharing it; the correction then becomes lecturer-reviewed minutes.
   Removal deletes it from retrieval. Replaying its already-processed chunk
   cannot recreate a removed segment. The record remains available after class
   through the normal student review and course-membership checks.

Use **Stop live transcription** before private conversation. Stop clears the
browser buffers, releases tracks and prevents further publication when the
backend notices the stopped lease. Native recognition already in progress may
finish in memory; it is not an audio recording or a continuing capture. Any text
already shared must be corrected/removed separately. In the narrow interval
where a database commit is already completing, a final segment may arrive; check
the record when stopping before a private discussion.

Hiding the tab, page exit, unmounting, microphone loss, processing failure and
queue overflow stop capture. Starting a microphone or server capture that was
cancelled cannot revive it when its async result arrives. It never automatically
restarts. Pausing/ending the class stops publication immediately at the server
check and stops browser capture at its next status poll (about 3 seconds). A
crashed browser's server lease expires after 90 seconds. Staff can stop an old
lease using **Stop existing capture** before starting again.

## Administrator setup

The feature is off by default. It does not require Graph transcript permission,
a Teams media bot or cloud speech credentials. The existing #176/#181 auth,
course/session, database and chatbot services must be configured.

For a Python deployment, install the optional speech dependencies and prepare
the pinned English model explicitly:

```sh
cd backend
pip install '.[transcription]'
python scripts/prepare_live_speech.py --output /absolute/model-directory
```

Set backend configuration:

```dotenv
LIVE_TRANSCRIPTION_ENABLED=true
LIVE_TRANSCRIPTION_MODEL_PATH=/absolute/model-directory
LIVE_TRANSCRIPTION_LANGUAGE=en
LIVE_TRANSCRIPTION_CPU_THREADS=2
```

`prepare_live_speech.py` downloads the MIT-licensed
`Systran/faster-whisper-base.en`, pinned to revision
`3d3d5dee26484f91867d81cb899cfcf72b96be6c`. Use a multilingual model prepared by
the administrator if another language is needed, and test it separately. Runtime
loading uses `local_files_only=True`, CPU int8, and disables ONNX telemetry;
no Hugging Face token is required and audio is not sent to Hugging Face.

For the demo Compose deployment, set the same variables with model path
`/data/models/faster-whisper-base.en`, build the backend with the speech extra,
and download into the existing private `/data` volume before starting capture:

```sh
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env build backend
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env run --rm --no-deps --entrypoint python backend scripts/prepare_live_speech.py --output /data/models/faster-whisper-base.en
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d
```

Run `alembic upgrade head` (the container entrypoint does this). It adds an origin
label to existing discussion notes, which remain lecturer-reviewed. Use HTTPS in
deployment; browser microphone capture works on HTTPS or localhost. The worklet
is served from the same origin. Do not insert speech model credentials/assets
into frontend variables. Local inference needs server CPU/RAM; this initial
implementation admits one native inference at a time and stops another capture
rather than queueing unbounded work.

## Privacy and consent change

This feature **sends lecturer microphone audio to the C.L.I.P server**. The
existing student gaze/VAD path still sends derived readings only and is unchanged.
Do not describe the new feature as on-device-only or consent to student attention
indicators as permission for live speech transcription.

Before enabling it for people, the institution/group must approve the privacy
notice and define the participant notification/consent process. The lecturer's
checkbox attests those requirements; it does not obtain agreement from each
participant. Microphones can pick up nearby students and loudspeaker audio.
Do not promise that only one person's voice will be captured.

Audio exists in short memory buffers on the browser/server while processed; it
is not written to the database, audio files, application logs or browser storage.
An inference already running may retain its input until it finishes after Stop
or a timeout. Model files persist, but contain no captured classroom audio.

Recognized text is **stored and shared automatically** with course students and
their chatbot before individual lecturer review. It may include personal content
or recognition errors. Emails/URLs are masked, unsafe instruction-bearing output
is refused, and SQL diagnostics hide bound values; names and all other personal
information cannot be reliably removed. Stop before private discussion. Staff
can correct/remove segments, including personal references that account erasure
cannot automatically locate in unstructured text. Text follows session retention,
purge and backup policies. Deleting a segment does not erase what students have
already read or an answer already displayed in their chat.

## Operational bounds and limitations

- No all-participant Teams capture, speaker identification, live Graph transcript
  access, automatic Teams recording or cloud speech provider.
- English base model by default. Recognition can be inaccurate for accents,
  technical vocabulary, silence/noise, overlapping voices and chunk boundaries.
  Never use the transcript as proof of attention, identity, attendance or grading.
- First text arrives after a full 10-second chunk plus processing. Students'
  record display refreshes every 5 seconds. Silence can produce no new entry.
- Input is bounded to 1–12 seconds of mono 16 kHz/16-bit PCM and 390,000 bytes.
  Captures accept chunks in sequence, with rate checks and no concurrent upload
  per lease. One lease has at most 1,200 chunks; the complete session record is
  capped at 1,400 entries (2,000 characters each). Capacity errors stop capture.
- Native ASR has a 25-second request deadline and one in-flight inference slot;
  cancellation retains that slot until the native worker actually finishes.
  At most two waiting chunks are buffered in the browser. Slow processing or
  network failure stops capture with a visible gap warning; speech is not silently
  discarded while showing a healthy recording state. Restart explicitly.
- Discussion retrieval is word-based. Broad recaps sample across a selected
  window rather than only its final chunks; their cited source limit means they
  can still omit material. The assistant must acknowledge incomplete/unreviewed
  transcripts. Lecture slide chat and reviewed minutes remain available.

## Validation

Validation on 7 November 2026:

- 404 backend tests passed across live speech, transcript import, discussion,
  tutor, security/route auditing and API contract checks.
- 85 additional related checks passed (2 existing skips), including repeated
  live/import coverage and retention, student review and sensor privacy. These
  overlap the first run and are not a separate unique-test total.
- 239 frontend unit tests passed; build, lint and browser TypeScript passed.
- 15 Chromium browser cases passed across live microphone and discussion flows,
  including moving time windows, startup cancellation and backlog shutdown.
- Migration downgrade/upgrade, committed API snapshot, Ruff checks and Compose
  configuration with speech enabled passed.

 Tests use disposable
PostgreSQL and synthetic browser media, not private meeting audio. They cover
staff/course access, sequence replay, teacher correction/removal, stopping during
inference, native-worker cancellation, audio format/size bounds and live speech
retrieval by chat. Browser tests exercise the real AudioWorklet/WAV path, stop,
visibility/page exit, session end, denial, pending-start cancellation, backpressure,
keyboard controls and automated WCAG checks.

A separate offline check used the upstream faster-whisper public `jfk.flac`
fixture (first 10 seconds) and the real pinned English model on this Mac. Cold
processing completed in approximately 4.82 seconds and recognized the expected
speech. This is a functional smoke check, not a class-quality benchmark. No personal microphone audio was used for this smoke check.

Actual lecturer microphone quality, sustained class-length load, weaker hardware,
HTTPS deployment and use alongside a real Teams meeting still need acceptance
on the intended server/devices. Keep the feature off until notice/consent and
that acceptance are ready.

References:
- [faster-whisper runtime](https://github.com/SYSTRAN/faster-whisper)
- [English model and license](https://huggingface.co/Systran/faster-whisper-base.en)
- [Upstream public ASR fixtures](https://github.com/SYSTRAN/faster-whisper/tree/master/tests/data)
- [Teams post-meeting transcript API](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/meeting-transcripts/overview-transcripts)
