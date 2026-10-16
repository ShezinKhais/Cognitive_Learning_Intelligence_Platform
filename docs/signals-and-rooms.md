# Attention signals and breakout rooms

Owner: General CS, Phase 6. Code: `backend/app/realtime/signals.py`,
`backend/app/realtime/rooms.py`, `backend/app/realtime/attention_windows.py`,
`backend/app/realtime/attention.py` and the watch in
`backend/app/realtime/classroom.py`; the events in `backend/app/api/v1/ws.py`.

A student's device works out a few numbers about the student every five
seconds and sends them as `signal.attention`. The server keeps the ones it
accepts in two places. A rolling window feeds Cyber 1's engagement scoring and
sends the student a private prompt when the reading stays low. The per-minute
summaries go to the analytics layer, and are described in
[attention-signals.md](attention-signals.md). The same events carry voice
activity, which, with the room each student says they are in (`room.confirm`),
tells the lecturer how each breakout room is doing (`room.status`, and an
`alert.raised` of kind `breakout_inactive` when a room has been silent too
long).

The rolling window, the rooms and the scores live in memory with the running
session, like the rest of the classroom. Nothing in them is a camera frame, a
sound or a word.

## What a device sends

Client events are `{ "type": ..., "data": ... }`. A student sends these on the
session socket (`/ws/session`, joined with a `session_id`).

### signal.attention

```json
{
  "type": "signal.attention",
  "data": {
    "gaze_on_screen_ratio": 0.82,
    "face_present": true,
    "speaking": false,
    "window_seconds": 5.0
  }
}
```

| Field | Rule |
|---|---|
| `gaze_on_screen_ratio` | 0 to 1, or null. The share of the window the student looked at the screen. |
| `face_present` | true, false or null. Whether a face was in view. |
| `speaking` | true, false or null. Voice activity, never speech. |
| `window_seconds` | More than 0 and at most 3600. The period the other fields summarise. |

Nothing else can travel on the event, so no frame or audio can leave the
device. A field the device cannot report is null or left out; absence is not a
low value.

The server does not take `window_seconds` on trust. It is cut to the time that
has really passed since the student's previous accepted signal, counted within
the clock minute, and the rolling window then counts a summary as covering at
most 30 seconds. A client cannot outweigh a minute of honest summaries with one
that says it describes an hour.

### room.confirm

```json
{ "type": "room.confirm", "data": { "room_label": "Room 1" } }
```

| Field | Rule |
|---|---|
| `room_label` | 1 to 100 characters. Whatever the student says the room is called. |

The student's word is the mapping: nothing guesses a room from Teams. A
label is cleaned (characters that are not printed become spaces, runs of
whitespace collapse, ends are trimmed, 100 characters at most) and matched
without regard to case or spacing, so "Room 1", "room 1" and " ROOM  1 " are
one room, shown as it was first spelt. A student moves by confirming another
room. Confirming the room they are already in changes nothing. A room left
empty is dropped.

### How often

The client should send one `signal.attention` every five seconds, and
`room.confirm` once on entering a room and again only if the student moves.

Two limits stand between a faster sender and the scoring, and they behave
differently.

**Per socket, in `ws.py`.** Each socket has a limit for each event:

| Event | Allowed |
|---|---|
| `signal.attention` | A burst of 5 together (a tab waking up), then one per `ATTENTION_SIGNAL_MIN_INTERVAL_SECONDS`. |
| `room.confirm` | A burst of 3, then one every 2 seconds. |

A frame over the limit is dropped before it takes the session's lock. The
sender is told with one `RATE_LIMITED` error, and not again for 10 seconds, so
a broken client does not double the traffic the limit is there to stop.

**Per student, in `attention_windows.py`.** A `signal.attention` that gets past
the socket limit but arrives less than 2 seconds after the student's last
accepted one is dropped, and nothing is sent back. This is fixed in code, and
it holds across sockets: a student with two tabs open is one student. A dropped
signal counts towards nothing. It is not in the rolling window, so it does not
move the score or the prompt decision, it is not in the minute's summary, and
its voice reading is not counted for the student's room.

The first limit protects the server, the second protects the evidence.

## What the server sends back

Server events are `{ "type": ..., "seq": 0, "ts": ..., "data": ... }`. Every
event below goes to named people, not the class, and carries `seq` 0: it is not
part of the ordered stream and is not replayed on reconnect. What a reconnecting
client needs is sent again when it joins (see "When a panel opens").

| Event | To | When |
|---|---|---|
| `prompt.attention` | The one student | Their signals stayed low, see "The private prompt". |
| `room.status` | Lecturer and admin sockets of the session | A room's status or membership changed, and each room as it stands when the socket joins. |
| `alert.raised` | Lecturer and admin sockets of the session | A room came to need attention. |
| `error` | The sender | A signal or confirmation was refused. |

Students are never sent `room.status` or `alert.raised`, and no event tells a
student which room they confirmed. `engagement.update` is in the contract but
is not sent: the contract does not say who receives it.

### prompt.attention

```json
{
  "type": "prompt.attention",
  "seq": 0,
  "ts": "2026-03-02T09:41:10Z",
  "data": {
    "prompt_id": "5b1e...",
    "message": "Quick check-in: are you still with the class?",
    "expires_at": "2026-03-02T09:42:10Z",
    "escalation": 1
  }
}
```

The student answers with `prompt.ack` (`{ "prompt_id": "...", "dismissed": false }`),
the event Phase 3 already handles. An answer to a prompt that has gone is
refused with `PROMPT_NOT_OPEN`.

### room.status

```json
{
  "type": "room.status",
  "seq": 0,
  "ts": "2026-03-02T09:50:00Z",
  "data": {
    "room_label": "Room 1",
    "status": "quiet",
    "members": 4,
    "speaking_now": 0,
    "silence_seconds": 75,
    "task_interactions": 2
  }
}
```

| Field | Meaning |
|---|---|
| `room_label` | The label as first spelt. |
| `status` | One of the statuses below. |
| `members` | Confirmed members who are connected now. A student who has left the class is not counted, and counts again if they come back. |
| `speaking_now` | Connected members whose latest fresh voice reading says speaking. |
| `silence_seconds` | Whole seconds since anyone in the room last spoke, counted as described below. 0 while someone is speaking and while the room is `unknown`. |
| `task_interactions` | Answers accepted from the room's members. A refused answer does not count. |

`room.status` is sent when a room is confirmed, and after that only when a
room's payload differs from what staff were last told. A room that is steady
is not repeated, but one that is silent changes `silence_seconds` at every
pass, so it is sent about once every `SIGNAL_WATCH_SECONDS` while the silence
grows. When a room empties because its last member moved, it is sent once
more with `members` 0 and status `unknown` so a panel can take it down. The
server checks every `SIGNAL_WATCH_SECONDS`, so a change shows up that late at
most, apart from a confirmation, which is reported at once.

### alert.raised

```json
{
  "type": "alert.raised",
  "seq": 0,
  "ts": "2026-03-02T09:53:00Z",
  "data": {
    "alert_id": "9c0d...",
    "kind": "breakout_inactive",
    "message": "Room 1 has been quiet for 3 minutes.",
    "reason": "No voice activity from 4 members for 180 seconds.",
    "confidence": 0.75,
    "explanation": "Nobody in this room has had voice activity for that long. This is worked out from whether each member's own device detects a voice. Nothing is recorded or listened to, and members who have not allowed the microphone are not heard at all, so a room working quietly looks the same as one that has stopped.",
    "explanation_source": "fallback",
    "confidence_reasons": [
      "3 of the room's 4 members are reporting voice activity.",
      "Silence is counted only from when the room was first heard."
    ],
    "recommendation": "Look in on the room to see whether the group needs help."
  }
}
```

No model is asked about a room: all of it is written by code from the counts.
`explanation_source` is `fallback`, which here means written by code and not by
a model. The fields are:

| Field | Value |
|---|---|
| `message` | "{label} has been quiet for N minute(s)." in whole minutes, or "for N seconds." when the silence is under a minute (a deployment with short limits). |
| `reason` | "No voice activity from N member(s) for S seconds." |
| `confidence` | The share of the room's connected members whose devices are reporting voice activity (0 to 1). A room heard through one member of five is known far less well than one heard through all of them. |
| `confidence_reasons` | "N of the room's M member(s) is/are reporting voice activity." and "Silence is counted only from when the room was first heard." |
| `explanation` | A fixed text saying how the reading is made, and that a room working quietly looks the same as one that has stopped. |
| `recommendation` | The automatic one for this kind: "Look in on the room to see whether the group needs help." |

"Reporting" means the member's device has reported on voice recently enough
(within `ROOM_VOICE_FRESH_SECONDS`), whether or not it heard anyone. A member
whose device has said nothing about voice, because the microphone is off or the
student has not allowed it, lowers the confidence and does not count as silent.

The alert is stored first (as `ai_alert`, kind `breakout_inactive`, with the
room label, member count and silence in `details`), so it is still there after
a refresh and once the session is over: `GET /sessions/{session_id}/alerts`
lists it and the acknowledge route works on it as for any alert. A store that
fails is logged and the lecturer is still told. It is raised once when a room
comes to need attention, and again only after the room has been `active` in
between.

### Errors

An `error` event has `data` of `{ "code": ..., "detail": ... }`.

| Code | When |
|---|---|
| `CONSENT_REQUIRED` | `signal.attention` from a student who has not consented to engagement monitoring. |
| `NOT_IN_SESSION` | `signal.attention` from anyone but a student connected to a running session; or `room.confirm` from a socket without a session, from staff, or for a session this process is not running. |
| `RATE_LIMITED` | Over the per-socket limits above. Sent at most once in 10 seconds per socket. |
| `ROOM_LIMIT` | A new room in a session that already has `MAX_ROOMS_PER_SESSION` of them. Joining an existing room, or moving out of a room of one, is still allowed. |
| `ROOM_LABEL_INVALID` | The label has nothing printable in it once cleaned. |
| `MALFORMED_EVENT` | The payload is out of bounds (for example `gaze_on_screen_ratio` of 1.5). |

A frame throttled before the consent check is dropped without a
`CONSENT_REQUIRED`. A signal dropped for arriving within 2 seconds of the last
is dropped without any error.

## When a panel opens

A lecturer or admin socket joining mid-class is sent one `room.status` for
each room as it stands, after `session.state` (`Classroom.welcome`), and is
told of changes after that. A panel opened or refreshed mid-class therefore
needs nothing but the socket. There is no REST route for rooms.

A session this process is not running has no rooms, so a socket joining before
the session starts, or after it ends or the server restarts, is sent none.

## How a room's status is worked out

Only two things are used: whether the room's members' devices report voice
activity, and whether they are answering questions. There is no audio or
transcript to use. Only signals the student's window accepted count (see "How
often"), after consent has removed what the student did not allow.

| Status | Meaning |
|---|---|
| `unknown` | No connected member has reported on voice recently enough. Not silence: a room where every member declined the microphone, or has not turned it on, has not been quiet. |
| `active` | Someone was speaking at the latest reading, or the room has been silent for less than `ROOM_QUIET_AFTER_SECONDS`. |
| `quiet` | Heard from, and silent for `ROOM_QUIET_AFTER_SECONDS` or more. |
| `needs_attention` | Silent for `ROOM_NEEDS_ATTENTION_AFTER_SECONDS` or more. |

A reading describes a member for `ROOM_VOICE_FRESH_SECONDS`; an older one no
longer counts as heard. Silence is counted from the last time anyone in the
room spoke, or from the moment the room started being heard, whichever is
later, never from before anyone was listening. If the room goes unheard and is
then heard again, the count starts again. A reading that says nothing about
voice (`speaking` null) changes nothing.

## The private prompt

Every `SIGNAL_WATCH_SECONDS` a running session that has had a signal or a room
looks at its signals. For each connected student who has consented to
monitoring it rescores them on what is known now, and sends them
`prompt.attention` only when all of these hold:

- Their signals cover at least `REFOCUS_MIN_SIGNAL_SECONDS` of the window
  (below). 0 turns prompting from signals off.
- The signals alone fall short of engaged: the mean of the gaze ratio and
  face presence, weighed equally, is below 0.6. A window with neither gaze nor
  a face is not low.
- Engagement scoring, on everything it knows, says at risk or disengaged and
  rests on at least two kinds of evidence, one of them participation (attempt
  rate, answer timing or prompt responses). That is Cyber 1's rule
  (`should_send_dynamic_prompt` in `services/engagement.py`): the camera alone
  is never enough, so a student who is answering is not prompted for looking
  away, and a student with a recorded accommodation is never prompted
  automatically.
- No prompt has been sent on the signals within `REFOCUS_COOLDOWN_SECONDS`.
- The limits every prompt obeys: the session is not paused, the student has no
  open question left to answer, no earlier prompt is waiting on them, and they
  have had fewer than `DYNAMIC_PROMPT_MAX_PER_STUDENT` this session.

The prompt goes to that student only. Staff are not told. It stays up for
`ATTENTION_PROMPT_TTL_SECONDS`. The cooldown is spent only when a prompt was
actually sent.

## From signals to a score

One five-second summary says where a student happened to be looking at that
moment. Scoring reads a rolling window instead:

- The window keeps the last 64 accepted summaries and reads the ones from the
  last 120 seconds (`ATTENTION_SIGNAL_MAX_AGE_SECONDS`). A camera closed early
  in the lecture does not keep counting.
- Gaze is the average of the summaries that reported it, each weighted by the
  time it covers (at most 30 seconds). A glance away is a small part of a
  minute, not the whole of the evidence.
- A face counts as present when it was for at least half the time that
  reported on it.
- Speaking is whether any summary heard a voice. Voice is not scored in either
  direction; it only feeds the rooms.
- The window's own length is the time covered, at most 120 seconds. Too little
  of it says nothing, so a student who has just turned the camera on is not
  judged on the first frame.

Scoring (`compute_engagement`, Cyber 1) is unchanged: the score is the mean of
the evidence available, a signal with no evidence is dropped and not counted as
zero, a student with only camera evidence is not scored, and the status is
`engaged` from 0.6, `at_risk` from 0.3 and `disengaged` below that,
`disengaged` needing two kinds of evidence. Gaze is read against the student's
own baseline, which learns from the window once per question close and once
per new signal, never from the watch.

The watch rescores between questions as well as at each question close, so
`GET /sessions/{session_id}/engagement` reflects the signals as they stand. As
before, the scores are held in memory with the running session.

## What is stored

Two things reach the database from this module.

- **Attention minutes.** Every signal the window accepts is also kept for its
  clock minute, and each finished minute is stored per student in
  `attention_signal_summary`, as described in
  [attention-signals.md](attention-signals.md). This is the only record of a
  student's signals, and it is what the analytics layer and reports read.
- **Room alerts.** A `breakout_inactive` alert is stored as above.

Nothing else is stored. The rolling window and the engagement scores are in
memory. A room's status is not stored. A student who has not consented to
monitoring has nothing stored about them.

## Consent

The gates are decided before a signal reaches the window, and applied again to
what is held when a consent is withdrawn.

| Consent | What it covers here |
|---|---|
| `terms` | Being in the class at all. Withdrawing it closes the student's session sockets (code 4003), which takes them out of every room's member count. |
| `engagement_monitoring` | Everything in this document about a student. Without it their signals are discarded (`CONSENT_REQUIRED`), no score is computed, no prompt is sent, nothing is stored, and their voice counts towards no room. |
| `camera` | `gaze_on_screen_ratio` and `face_present`. Without it they are dropped from every signal. |
| `microphone` | `speaking`. Without it it is dropped, and the student's voice counts towards no room. |

Declining one never blocks another, and scoring renormalises over what is left,
so declining never lowers a score.

Withdrawing takes effect at once, in every class the process runs, not at the
next reconnect:

- Engagement monitoring: everything held about the student's engagement is
  dropped, including the minute not yet stored, the prompt waiting on them is
  taken down, and what their room heard from them is forgotten. The count of
  prompts they have been sent is kept, so the cap holds if they agree again.
- Camera: the gaze and face parts of their held signals are dropped. What the
  room heard stays.
- Microphone: the speaking part is dropped, and what the room heard from them
  is forgotten.

In each case the student stays in the room they confirmed; the room becomes
`unknown` if nobody else has been heard. A grant is picked up at the next join,
read from the store.

## Privacy

- Only derived numbers travel: a ratio, two flags and a duration. No event type
  can carry a frame, a sound or text.
- Room status and room alerts go to staff only. Nobody else is sent them.
- Prompts are private to the student they are for.
- A room nobody has been heard from is `unknown`, never `quiet`.
- Nothing is kept about a student who has not consented to monitoring.
- The room label is typed by the student. It appears in the lecturer's alert
  text and is stored with the alert.

## Settings

All are in `backend/app/core/config.py` and can be set in `backend/.env`.

| Setting | Default | Meaning |
|---|---|---|
| `ATTENTION_SIGNAL_MIN_INTERVAL_SECONDS` | 2.0 | Least time between `signal.attention` frames on one socket, after the burst of 5. 0 turns the limit off. It does not change the fixed 2 second rule per student. |
| `SIGNAL_WATCH_SECONDS` | 10.0 | How often a running session rescores its signals and checks its rooms. |
| `REFOCUS_MIN_SIGNAL_SECONDS` | 45.0 | Signal time that must be in the last two minutes before signals alone may prompt a student. 0 turns prompting from signals off. |
| `REFOCUS_COOLDOWN_SECONDS` | 300.0 | Least time between two prompts sent on the signals alone to one student. |
| `ROOM_VOICE_FRESH_SECONDS` | 20.0 | How long one voice reading describes a member. |
| `ROOM_QUIET_AFTER_SECONDS` | 60.0 | Silence before a room is `quiet`. |
| `ROOM_NEEDS_ATTENTION_AFTER_SECONDS` | 180.0 | Silence before a room is `needs_attention` and the lecturer is alerted. Must be greater than `ROOM_QUIET_AFTER_SECONDS`, or the app refuses to start. |
| `MAX_ROOMS_PER_SESSION` | 50 | Rooms one session may have. |

Related, from earlier phases: `DYNAMIC_PROMPT_MAX_PER_STUDENT` (3) and
`ATTENTION_PROMPT_TTL_SECONDS` (60).

The signal time in the last two minutes can never exceed 120 seconds, and a
student sending every 5 seconds covers close to that. The default
`REFOCUS_MIN_SIGNAL_SECONDS` of 45 is reached after about 45 seconds of steady
signals.

## For the other workstreams

**AI 2 (student client).** Send `signal.attention` every five seconds with the
numbers worked out on the device, only while the student has agreed to the
matching consents (the server drops the rest anyway). Leave a field null when
the device cannot report it. Do not send faster: the socket allows a burst of
5 and then one per `ATTENTION_SIGNAL_MIN_INTERVAL_SECONDS`, a second
`RATE_LIMITED` is not sent for 10 seconds, and anything under 2 seconds after
the last is ignored without a reply. Send `room.confirm` when the student
picks or changes their room; there is no reply on success, so keep the label in
the client. Handle `prompt.attention` and answer with `prompt.ack`. Expect
`error` events with the codes above.

**Cyber 2 (lecturer panel).** Rooms reach the panel over the WebSocket only.
When the lecturer's socket joins, the server sends one `room.status` for each
room as it stands, so a panel that has just opened or refreshed already has the
list. Apply each later `room.status` by `room_label`, and take a room down when
its `members` is 0. Show `unknown` as unknown, not quiet. `alert.raised` with
kind `breakout_inactive` arrives live and is also in
`GET /sessions/{session_id}/alerts`. A room that is `needs_attention`
when the panel joins is shown by its `room.status`, but an alert already raised
for it is not sent again: read the alerts route for it.

**Cyber 1.** The prompt gate calls your `compute_engagement` and
`should_send_dynamic_prompt`; the thresholds (0.6, 0.3), `MIN_SIGNALS_FOR_PROMPT`
and `ATTENTION_SIGNAL_MAX_AGE_SECONDS` (the window) are yours. The watch adds
only the minimum signal time, the cooldown and the check that the signals
themselves are low. Your personal baseline is fed the window's summary rather
than a single reading, and the watch passes your accommodation flag to the
scorer as a question close does.

**BBIS.** Attention reaches your layer as the per-minute summaries in
`attention_signal_summary`, through the `AttentionRecorder` seam described in
[attention-signals.md](attention-signals.md). Room alerts go through the
`AlertRecorder` as `ai_alert` rows. Nothing here writes engagement scores to the database.

**AI 1.** Nothing here calls a model.

## Not done here

- Rooms and signals live in memory with the running session and are lost on
  restart. A restarted session has no rooms until students confirm again, and
  a room's silence count starts again.
- No event tells a student which room they confirmed. The server does not
  check a label against Teams or any list.
- `engagement.update` is in the contract but is not emitted, because the
  contract does not say who receives it.
- Room status is not stored. Only the alert is, so a session report cannot show
  how a room did, only that an alert was raised.
- A student is not removed from a room when they leave the class; they stop
  counting while disconnected and count again on return.
- Nothing in the frontend sends these events or shows these panels yet.
- One process: the limits and windows are per process, as the classroom is.
