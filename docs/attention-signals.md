# Attention signals: from the student's device to the analytics layer

Owner: General CS, Phase 6 (#59). Code: `backend/app/realtime/attention_windows.py`,
`backend/app/realtime/attention.py`, `Classroom.record_attention` in
`backend/app/realtime/classroom.py`, and `_AttentionSummaries` in
`backend/app/services/live_wiring.py`.

A student who opts in sends `signal.attention` over the session WebSocket about
every five seconds (AI 2, #136). The signal carries only derived indicators. It
never carries an image, audio, landmarks or a transcript, and the frozen schema
has no field for any of them. This page is what happens to those signals on the
server.

## The message

`signal.attention` is unchanged from the frozen contract (`events.schema.json`):

| Field | Meaning |
|---|---|
| `gaze_on_screen_ratio` | 0 to 1, or null when there is no camera reading. |
| `face_present` | true, false or null. |
| `speaking` | Voice activity only, not speech content. true, false or null. |
| `window_seconds` | How long the values cover. More than 0 and at most 3600. |

Null always means "no reading". It never means zero, and it is stored as null.

## What the server does with each signal

1. **Who may send.** Only a student connected to a running session, holding
   `engagement_monitoring` consent. Anyone else gets `CONSENT_REQUIRED` or
   `NOT_IN_SESSION`.
2. **Consent per field.** Without camera consent, gaze and face are removed.
   Without microphone consent, speaking is removed (`permitted_signal`,
   Cyber 1).
3. **Rate.** A signal less than 2 seconds after the student's last kept one is
   dropped without an error. No error is sent, so a fast client does not get a
   stream of error banners.
4. **Duration.** `window_seconds` is reduced to the part of the current minute
   since the student's previous signal, or since the minute began for their
   first signal in it. One signal cannot count for more time than really
   passed, and a minute's signals never add up to more than a minute.
5. **Kept twice.**
   - In a rolling window for engagement scoring (Cyber 1): the last two
     minutes of the student's signals, each weighted by the time it covers.
     See [signals-and-rooms.md](signals-and-rooms.md).
   - Every signal in the current clock minute is kept for storing.

A signal dropped by the rate rule counts towards neither, nor towards the
student's breakout room.

## Per-minute summaries

At the end of each clock minute, every student's signals for that minute go to
the `AttentionRecorder`. The minute is handed over when the next signal from
anyone arrives in a later minute, and when the session ends. There is no
background timer.

- The recorder folds the signals with BBIS's `summarise()` and writes one
  `attention_signal_summary` row per student per minute with `save_summary()`
  (#139).
- The write runs in the background. The student whose signal ended the minute
  is never held up by it, so their next answer is never delayed. Ending a
  session, or shutting the app down, waits for writes still in progress.
- A failed or slow write (more than 5 seconds) is logged and dropped. The class
  is not affected.
- A minute that is already stored is skipped, and only that minute is lost.
- A user with no student record is skipped.
- A pause stores nothing. The minute it falls in is stored once, when it ends.
- Lost on a restart: the minute in progress, at most 60 seconds.

`face_present_ratio` and `speaking_ratio` are the share of signals in the
minute, weighted by duration, that reported a face or voice. The client sets
`face_present` and `speaking` to true if the face or voice was there at any
point in its five seconds. So these are shares of five-second windows, not
exact shares of time.

Production refuses to start without an `AttentionRecorder`, like the other
recorders, and `install_live_store` registers one.

## Consent changes during a class

- **Granted:** it applies once the consent route has committed it together with
  its audit record. If either fails, the grant is neither stored nor applied.
  Before #59, a grant only took effect when the student
  next joined. Until then, every signal from a student who opted in during class
  was refused with `CONSENT_REQUIRED`.
- **Monitoring withdrawn:** the minute in progress is dropped and never stored,
  along with all other engagement evidence. One narrow gap remains: a finished
  minute already handed to the recorder (its write takes at most 5 seconds) is
  still stored if the withdrawal arrives during that write. It holds only
  signals sent while consent was given.
- **Camera or microphone withdrawn:** those fields are removed from the minute
  in progress, as well as from the rolling window. Withdrawing the microphone
  also clears what the student's breakout room heard from them.

## Refocus prompts

Refocus prompts are private. They go only to the one student, outside the
replayed sequence, with a per-student cap, an expiry and a recorded outcome.
They are sent after missed questions, when engagement scoring flags a student
at a question close, and between questions when the student's own signals
have stayed low. That last one, and the breakout rooms the same signals feed,
are described in [signals-and-rooms.md](signals-and-rooms.md).

## Not done yet

- **A class-level push to the lecturer.** The lecturer's panel (#141) polls
  `GET /sessions/{id}/engagement`. Breakout rooms are pushed as `room.status`,
  but a pushed class engagement summary would be a contract addition for the
  group to agree.
- **Telling the client when consent is withdrawn.** The client finds out by
  polling. A `consent.changed` event would be a contract addition.
- **Rejecting unknown fields in `signal.attention`.** They are dropped, not
  stored, but not refused. Tightening the schema changes the frozen contract.
- **A cap on WebSocket message size.** Uvicorn's default of 16 MiB applies.
  The deployment should start it with `--ws-max-size 65536`; the largest
  legitimate message (a free-text answer) is far smaller.
- **Retention.** The purge runner is scheduled (see [reports.md](reports.md)).
  Purging summaries older than `DATA_RETENTION_DAYS` needs BBIS to register a
  purge task for `attention_signal_summary`.
