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
4. **Duration.** `window_seconds` is reduced to the time since the student's
   previous signal, and to at most 60 seconds. One signal cannot count for more
   time than really passed.
5. **Kept twice.**
   - The latest signal is kept for engagement scoring (Cyber 1), as before.
   - Every signal in the current clock minute is kept for storing.

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
  session waits for writes still in progress.
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

- **Granted:** it applies once the consent route has committed it and read it
  back from the store. Before #59, a grant only took effect when the student
  next joined. Until then, every signal from a student who opted in during class
  was refused with `CONSENT_REQUIRED`.
- **Monitoring withdrawn:** the minute in progress is dropped and never stored,
  along with all other engagement evidence.
- **Camera or microphone withdrawn:** those fields are removed from the minute
  in progress, as well as from the latest signal.

## Refocus prompts

Refocus prompts are unchanged and already private. They go only to the one
student, outside the replayed sequence, with a per-student cap, an expiry and
a recorded outcome. They are sent after missed questions, and when engagement
scoring flags a student at a question close.

## Not done yet

- **Prompts from attention signals alone.** A prompt between questions, based
  only on a student's attention minutes, needs Cyber 1 to agree a rule (#64).
- **A class-level push to the lecturer.** The lecturer's panel (#141) polls
  `GET /sessions/{id}/engagement`. With breakout rooms cut, `room.status` is
  never sent. A pushed class summary would be a contract addition for the group
  to agree.
- **Telling the client when consent is withdrawn.** The client finds out by
  polling. A `consent.changed` event would be a contract addition.
- **Rejecting unknown fields in `signal.attention`.** They are dropped, not
  stored, but not refused. Tightening the schema changes the frozen contract.
- **Retention.** Purging summaries older than `DATA_RETENTION_DAYS` belongs to
  the Phase 7 purge runner (#65).
