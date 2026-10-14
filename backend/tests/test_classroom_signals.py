"""Phase 6 in the classroom: attention signals aggregated and watched, the
private refocus prompt, and breakout rooms.

Owner: General CS, Phase 6.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.realtime import classroom as classroom_module
from app.realtime.classroom import (
    REFOCUS_PROMPT_MESSAGE,
    ROOM_LABEL_INVALID,
    ROOM_LIMIT,
    ROOM_NOT_IN_SESSION,
    Classroom,
)
from app.realtime.hub import Connection
from app.realtime.recorders import RoomAlert
from app.schemas.events import (
    AttentionSignalPayload,
    PromptAckPayload,
    RoomConfirmPayload,
    RoomStatus,
    ServerEventType,
)
from app.schemas.identity import ConsentType, Role
from app.schemas.session import SessionStatus

from .classroom_support import (
    FakeSocket,
    answer_to,
    deliver_next,
    join_as,
    make_room,
    make_row,
)

pytestmark = pytest.mark.usefixtures("fake_session_repository")

# Half past the minute: a student's first signal in a minute is held to the
# time since the minute began (attention_windows.py), and from here a
# five-second signal keeps all five.
T0 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
# Between two signals from one student, as the client sends them. Anything
# under two seconds apart is dropped as too soon.
SIGNAL_EVERY = 5.0
TERMS = ConsentType.TERMS
MONITORING = ConsentType.ENGAGEMENT_MONITORING
CAMERA = ConsentType.CAMERA
MICROPHONE = ConsentType.MICROPHONE


def _signal(
    gaze: float | None = None,
    face: bool | None = None,
    speaking: bool | None = None,
    seconds: float = 5.0,
) -> AttentionSignalPayload:
    return AttentionSignalPayload(
        gaze_on_screen_ratio=gaze, face_present=face, speaking=speaking, window_seconds=seconds
    )


# Looking away and nobody in view, which Cyber 1's rule counts as two kinds of
# evidence that the student has left.
AWAY = _signal(gaze=0.0, face=False)
ATTENTIVE = _signal(gaze=0.9, face=True)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


_CLOCKS: list[_Clock] = []


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Time that moves only when a test moves it: by SIGNAL_EVERY between two
    signals, and by however long a room test needs to be silent. Question
    windows still close on time, since their timers sleep until a moment
    worked out from this clock."""
    fake = _Clock()
    monkeypatch.setattr(classroom_module, "_now", fake)
    _CLOCKS[:] = [fake]
    return fake


class _AlertLog:
    """An AlertRecorder that keeps room alerts, or fails to."""

    def __init__(self, fail: bool = False) -> None:
        self.room_alerts: list[RoomAlert] = []
        self.calls = 0
        self._fail = fail

    async def record_alert(self, alert: object) -> None:
        return None

    async def record_room_alert(self, alert: RoomAlert) -> None:
        self.calls += 1
        if self._fail:
            raise RuntimeError("the store is down")
        self.room_alerts.append(alert)


async def _class(**settings: float):  # noqa: ANN202
    room, events = make_room(**settings)  # type: ignore[arg-type]
    row = make_row()
    room.activate(row.session_id)
    return room, events, row


async def _record(room: Classroom, row, student: UUID, *signals: AttentionSignalPayload) -> None:  # noqa: ANN001
    """Send the signals SIGNAL_EVERY apart, as the student's device would."""
    for number, signal in enumerate(signals):
        if number:
            _CLOCKS[0].advance(SIGNAL_EVERY)
        assert await room.record_attention(row.session_id, student, signal)


async def _watch(room: Classroom, row) -> None:  # noqa: ANN001
    live = room.get_running(row.session_id)
    assert live is not None
    await room.watch_once(live)


async def _close(room: Classroom, row, *answering: UUID) -> None:  # noqa: ANN001
    question = await deliver_next(room, row)
    for student in answering:
        assert (
            await room.submit(
                row.session_id, student, Role.STUDENT, answer_to(question.question_id)
            )
        ).accepted
    await asyncio.sleep(0.15)


async def _confirm(room: Classroom, row, student: UUID, label: str = "Room 1") -> str | None:  # noqa: ANN001
    return await room.confirm_room(row.session_id, student, RoomConfirmPayload(room_label=label))


def _prompts(socket: FakeSocket) -> list[dict]:
    return socket.of(ServerEventType.PROMPT_ATTENTION)


def _told(staff: FakeSocket) -> list[tuple[str, int]]:
    """The (status, silence) of each room.status a panel was sent."""
    return [
        (m["data"]["status"], m["data"]["silence_seconds"])
        for m in staff.of(ServerEventType.ROOM_STATUS)
    ]


# -- several signals are one reading --------------------------------------------------


async def test_a_score_rests_on_the_average_of_the_signals_not_the_last() -> None:
    room, events, row = await _class(window=0.05)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, *[_signal(gaze=1.0)] * 4, _signal(gaze=0.0))

    await _close(room, row)

    [scored] = room.engagement(row.session_id)
    # Four summaries at 1.0 and one at 0.0, each five seconds: 20 / 25.
    assert scored.engagement.signals_available == ["gaze"]
    assert scored.engagement.score == 0.8
    await room.shutdown()


async def test_the_watch_rescores_between_questions_from_the_signals_alone() -> None:
    room, events, row = await _class()
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, ATTENTIVE)
    assert room.engagement(row.session_id) == []

    await _watch(room, row)

    [scored] = room.engagement(row.session_id)
    assert scored.user_id == student
    assert scored.engagement.signals_available == ["gaze", "face_presence"]
    assert scored.engagement.score == pytest.approx(0.95)
    await room.shutdown()


async def test_a_student_who_has_left_is_not_rescored_by_the_watch() -> None:
    room, events, row = await _class()
    socket = FakeSocket()
    student = uuid4()
    connection = Connection(socket, student, row.session_id, Role.STUDENT)  # type: ignore[arg-type]
    await events.join(connection)
    await _record(room, row, student, ATTENTIVE)
    await events.leave(connection)

    await _watch(room, row)

    assert room.engagement(row.session_id) == []
    await room.shutdown()


# -- the refocus prompt -----------------------------------------------------------------


async def test_a_student_looking_away_with_no_face_in_view_is_prompted_once_and_privately() -> None:
    room, events, row = await _class(refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    classmate, _ = await join_as(events, row.session_id, Role.STUDENT)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    await _record(room, row, student, AWAY, AWAY)

    await _watch(room, row)
    await _watch(room, row)

    [prompt] = _prompts(socket)
    assert prompt["seq"] == 0
    assert prompt["data"]["message"] == REFOCUS_PROMPT_MESSAGE
    assert prompt["data"]["escalation"] == 1
    assert classmate.sent == [] and lecturer.sent == []
    await room.shutdown()


async def test_no_second_prompt_from_the_signals_inside_the_cooldown() -> None:
    room, events, row = await _class(refocus_after=10.0, refocus_cooldown=300.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)
    await _watch(room, row)
    [first] = _prompts(socket)
    # Answered, so that nothing but the cooldown stands in the way of another.
    ack = PromptAckPayload(prompt_id=UUID(first["data"]["prompt_id"]))
    assert await room.acknowledge_prompt(row.session_id, student, ack)

    await _watch(room, row)

    assert len(_prompts(socket)) == 1
    await room.shutdown()


async def test_another_prompt_follows_once_there_is_no_cooldown_to_wait_out() -> None:
    room, events, row = await _class(refocus_after=10.0, refocus_cooldown=0.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)
    await _watch(room, row)
    [first] = _prompts(socket)
    ack = PromptAckPayload(prompt_id=UUID(first["data"]["prompt_id"]))
    assert await room.acknowledge_prompt(row.session_id, student, ack)

    await _watch(room, row)

    assert len(_prompts(socket)) == 2
    await room.shutdown()


async def test_no_prompt_while_the_window_covers_too_little_of_the_minute() -> None:
    room, events, row = await _class(refocus_after=45.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)

    await _watch(room, row)

    assert _prompts(socket) == []
    # Still rescored: the student is simply not judged on ten seconds.
    assert [s.user_id for s in room.engagement(row.session_id)] == [student]
    await room.shutdown()


async def test_low_gaze_alone_is_not_enough_for_a_prompt() -> None:
    """Gaze is one kind of evidence; Cyber 1's rule asks for two."""
    room, events, row = await _class(refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, _signal(gaze=0.0), _signal(gaze=0.0))

    await _watch(room, row)

    assert _prompts(socket) == []
    [scored] = room.engagement(row.session_id)
    assert (scored.engagement.score, scored.engagement.signals_available) == (0.0, ["gaze"])
    await room.shutdown()


async def test_no_prompt_from_the_signals_when_the_threshold_is_zero() -> None:
    room, events, row = await _class(refocus_after=0.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)

    await _watch(room, row)

    assert _prompts(socket) == []
    await room.shutdown()


async def test_no_prompt_while_the_session_is_paused() -> None:
    room, events = make_room(refocus_after=10.0)
    row = make_row()
    room.activate(row.session_id, paused=True)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)

    await _watch(room, row)

    assert _prompts(socket) == []
    await room.shutdown()


async def test_no_prompt_over_a_question_the_student_has_still_to_answer() -> None:
    room, events, row = await _class(refocus_after=10.0, window=30.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)
    question = await deliver_next(room, row)

    await _watch(room, row)
    assert _prompts(socket) == []

    # Answered, the question no longer stands in the way.
    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))
    await _watch(room, row)
    assert len(_prompts(socket)) == 1
    await room.shutdown()


async def test_a_student_who_declined_monitoring_is_never_prompted_from_signals() -> None:
    room, events, row = await _class(refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)
    # Declined on another device since: the registry is told, the window is not.
    room.consents.set(student, {TERMS, CAMERA, MICROPHONE})

    await _watch(room, row)

    assert _prompts(socket) == []
    assert room.engagement(row.session_id) == []
    await room.shutdown()


async def test_a_student_who_never_consented_has_no_signals_to_prompt_on() -> None:
    room, events, row = await _class(refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    room.consents.set(student, {TERMS})

    assert not await room.record_attention(row.session_id, student, AWAY)
    await _watch(room, row)

    assert _prompts(socket) == []
    await room.shutdown()


async def test_a_student_who_is_looking_at_the_screen_is_never_prompted() -> None:
    room, events, row = await _class(refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, ATTENTIVE, ATTENTIVE, ATTENTIVE)

    await _watch(room, row)
    await _watch(room, row)

    assert _prompts(socket) == []
    await room.shutdown()


@pytest.mark.parametrize(("signal", "prompted"), [(ATTENTIVE, False), (AWAY, True)])
async def test_the_signals_must_be_low_themselves_not_only_the_score(
    signal: AttentionSignalPayload, prompted: bool
) -> None:
    """Missed questions and an ignored prompt put a student at risk on their
    own. That is engagement scoring's prompt to send after a question; the
    refocus prompt is about the signals, so a student whose device says they
    are watching is not sent one."""
    room, events, row = await _class(refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    live = room.get_running(row.session_id)
    assert live is not None
    now = classroom_module._now()  # noqa: SLF001
    live.attention.score({student}, set(), {}, now)
    live.attention.score({student}, set(), {}, now)
    ignored = live.attention.issue(student, "x", limit=5, ttl=timedelta(seconds=1), now=now)
    assert ignored is not None and live.attention.expire(ignored)
    await _record(room, row, student, signal, signal, signal)

    await _watch(room, row)

    scored = live.attention.rescore(student, classroom_module._now())  # noqa: SLF001
    assert scored.engagement.status.value in ("at_risk", "disengaged")
    assert len(_prompts(socket)) == int(prompted)
    await room.shutdown()


async def test_ending_the_session_nudges_nobody() -> None:
    room, events, row = await _class(window=30.0, refocus_after=10.0)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, AWAY, AWAY)
    question = await deliver_next(room, row)
    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))

    await room.end(row.session_id, SessionStatus.ENDED, 1)

    assert _prompts(socket) == []


# -- breakout rooms: confirming ----------------------------------------------------------


async def test_confirming_a_room_is_refused_for_anyone_who_is_not_a_connected_student() -> None:
    room, events, row = await _class()
    _, lecturer = await join_as(events, row.session_id, Role.LECTURER)
    payload = RoomConfirmPayload(room_label="Room 1")

    assert await room.confirm_room(uuid4(), uuid4(), payload) == ROOM_NOT_IN_SESSION
    assert await room.confirm_room(row.session_id, lecturer, payload) == ROOM_NOT_IN_SESSION
    assert await room.confirm_room(row.session_id, uuid4(), payload) == ROOM_NOT_IN_SESSION
    assert room.rooms(row.session_id) == []
    await room.shutdown()


async def test_a_label_with_nothing_printable_in_it_is_refused() -> None:
    room, events, row = await _class()
    _, student = await join_as(events, row.session_id, Role.STUDENT)

    assert await _confirm(room, row, student, "\x00\x07") == ROOM_LABEL_INVALID
    assert room.rooms(row.session_id) == []
    await room.shutdown()


async def test_a_session_at_its_room_limit_refuses_a_new_room() -> None:
    room, events, row = await _class(max_rooms=1)
    _, first = await join_as(events, row.session_id, Role.STUDENT)
    _, second = await join_as(events, row.session_id, Role.STUDENT)
    assert await _confirm(room, row, first, "A") is None

    assert await _confirm(room, row, second, "B") == ROOM_LIMIT
    assert await _confirm(room, row, second, "a") is None

    [only] = room.rooms(row.session_id)
    assert (only.room_label, only.members) == ("A", 2)
    await room.shutdown()


async def test_staff_are_told_of_a_room_when_it_is_confirmed_and_students_are_not() -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    admin, _ = await join_as(events, row.session_id, Role.ADMIN)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    classmate, _ = await join_as(events, row.session_id, Role.STUDENT)

    assert await _confirm(room, row, student) is None

    for staff in (lecturer, admin):
        [told] = staff.of(ServerEventType.ROOM_STATUS)
        assert told["seq"] == 0
        assert told["data"] == {
            "room_label": "Room 1",
            "status": "unknown",
            "members": 1,
            "speaking_now": 0,
            "silence_seconds": 0,
            "task_interactions": 0,
        }
    assert socket.sent == [] and classmate.sent == []
    await room.shutdown()


async def test_the_rooms_of_an_unknown_session_are_none() -> None:
    room, _, _ = await _class()

    assert room.rooms(uuid4()) == []
    await room.shutdown()


# -- breakout rooms: how they are doing ---------------------------------------------------


async def test_a_rooms_status_moves_from_unknown_to_active_to_quiet_to_needs_attention(
    clock: _Clock,
) -> None:
    room, events, row = await _class(voice_fresh=1000.0)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    assert await _confirm(room, row, student) is None
    await _record(room, row, student, _signal(speaking=True))
    await _watch(room, row)

    for later in (30, 30, 120):
        clock.advance(later)
        await _record(room, row, student, _signal(speaking=False))
        await _watch(room, row)

    assert _told(lecturer) == [
        ("unknown", 0),
        ("active", 0),
        ("active", 30),
        ("quiet", 60),
        ("needs_attention", 180),
    ]
    await room.shutdown()


async def test_a_status_that_has_not_changed_is_not_sent_again(clock: _Clock) -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)
    await _record(room, row, student, _signal(speaking=True))
    await _watch(room, row)
    told = len(lecturer.of(ServerEventType.ROOM_STATUS))

    await _watch(room, row)
    await _watch(room, row)

    assert told == 2
    assert len(lecturer.of(ServerEventType.ROOM_STATUS)) == told
    await room.shutdown()


async def test_a_room_left_empty_by_a_move_is_reported_once_with_nobody_in_it() -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student, "A")

    await _confirm(room, row, student, "B")
    await _watch(room, row)
    await _watch(room, row)

    told = [m["data"] for m in lecturer.of(ServerEventType.ROOM_STATUS)]
    assert [(t["room_label"], t["members"]) for t in told] == [("A", 1), ("B", 1), ("A", 0)]
    assert told[2]["status"] == "unknown"
    assert [s.room_label for s in room.rooms(row.session_id)] == ["B"]
    await room.shutdown()


async def test_a_student_who_disconnects_stops_counting_as_a_member() -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    stays, stayer = await join_as(events, row.session_id, Role.STUDENT)
    leaver = uuid4()
    connection = Connection(FakeSocket(), leaver, row.session_id, Role.STUDENT)  # type: ignore[arg-type]
    await events.join(connection)
    await _confirm(room, row, stayer)
    await _confirm(room, row, leaver)
    assert room.rooms(row.session_id)[0].members == 2

    await events.leave(connection)
    await _watch(room, row)

    assert room.rooms(row.session_id)[0].members == 1
    assert [m["data"]["members"] for m in lecturer.of(ServerEventType.ROOM_STATUS)] == [1, 2, 1]
    await room.shutdown()


async def test_answers_by_a_member_count_as_the_rooms_task_interactions() -> None:
    room, events, row = await _class(window=30.0)
    member_socket, member = await join_as(events, row.session_id, Role.STUDENT)
    _, outsider = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, member)
    question = await deliver_next(room, row)

    first = await room.submit(row.session_id, member, Role.STUDENT, answer_to(question.question_id))
    again = await room.submit(row.session_id, member, Role.STUDENT, answer_to(question.question_id))
    other = await room.submit(
        row.session_id, outsider, Role.STUDENT, answer_to(question.question_id)
    )

    # A refused answer is not the task being done.
    assert (first.accepted, again.accepted, other.accepted) == (True, False, True)
    assert member_socket.of(ServerEventType.ANSWER_RECEIPT)
    assert [s.task_interactions for s in room.rooms(row.session_id)] == [1]
    await room.shutdown()


# -- breakout rooms: the alert ------------------------------------------------------------


async def _silent_room(clock: _Clock, **settings: float):  # noqa: ANN202
    """A room whose only member has been heard not speaking, 180 seconds ago."""
    room, events, row = await _class(voice_fresh=1000.0, **settings)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)
    await _record(room, row, student, _signal(speaking=False))
    await _watch(room, row)
    clock.advance(180)
    return room, row, lecturer, student


async def test_a_room_silent_too_long_raises_a_breakout_alert_to_staff_once(clock: _Clock) -> None:
    room, row, lecturer, _ = await _silent_room(clock)
    log = room.alert_recorder = _AlertLog()
    assert lecturer.of(ServerEventType.ALERT_RAISED) == []

    await _watch(room, row)
    clock.advance(10)
    await _watch(room, row)

    [raised] = lecturer.of(ServerEventType.ALERT_RAISED)
    assert raised["seq"] == 0
    assert raised["data"]["kind"] == "breakout_inactive"
    assert raised["data"]["message"] == "Room 1 has been quiet for 3 minutes."
    assert raised["data"]["reason"] == "No voice activity from 1 member for 180 seconds."
    [stored] = log.room_alerts
    assert str(stored.alert_id) == raised["data"]["alert_id"]
    assert (stored.session_id, stored.room_label) == (row.session_id, "Room 1")
    assert (stored.members, stored.silence_seconds) == (1, 180)
    await room.shutdown()


async def test_a_room_alert_says_how_it_was_measured_and_how_far_to_trust_it(
    clock: _Clock,
) -> None:
    """Heard through one member of four, a room is known far less well than
    one heard through all of them, and the alert says so. It is a working
    alert, so it does not carry the text of one that could not be explained."""
    room, events, row = await _class(voice_fresh=1000.0)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    members = [(await join_as(events, row.session_id, Role.STUDENT))[1] for _ in range(4)]
    for member in members:
        await _confirm(room, row, member)
    await _record(room, row, members[0], _signal(speaking=False))
    await _watch(room, row)
    clock.advance(200)

    await _watch(room, row)

    [raised] = lecturer.of(ServerEventType.ALERT_RAISED)
    alert = raised["data"]
    assert alert["confidence"] == 0.25
    assert alert["explanation"] == classroom_module.ROOM_ALERT_EXPLANATION
    assert alert["explanation_source"] == "fallback"
    assert alert["confidence_reasons"][0] == (
        "1 of the room's 4 members is reporting voice activity."
    )
    assert "could not produce" not in alert["explanation"]
    assert alert["recommendation"]
    await room.shutdown()


async def test_a_room_that_falls_silent_again_after_speaking_is_alerted_again(
    clock: _Clock,
) -> None:
    room, row, lecturer, student = await _silent_room(clock)
    await _watch(room, row)
    assert len(lecturer.of(ServerEventType.ALERT_RAISED)) == 1

    await _record(room, row, student, _signal(speaking=True))
    await _watch(room, row)
    assert len(lecturer.of(ServerEventType.ALERT_RAISED)) == 1
    # Silent again, three minutes on: the last voice was at the clock's present.
    clock.advance(SIGNAL_EVERY)
    await _record(room, row, student, _signal(speaking=False))
    clock.advance(180)
    await _watch(room, row)

    assert len(lecturer.of(ServerEventType.ALERT_RAISED)) == 2
    await room.shutdown()


async def test_a_member_arriving_can_be_what_shows_a_room_has_been_silent_too_long(
    clock: _Clock,
) -> None:
    room, row, lecturer, _ = await _silent_room(clock)
    log = room.alert_recorder = _AlertLog()
    events = room._hub
    _, newcomer = await join_as(events, row.session_id, Role.STUDENT)

    assert await _confirm(room, row, newcomer) is None

    assert len(lecturer.of(ServerEventType.ALERT_RAISED)) == 1
    assert [a.members for a in log.room_alerts] == [2]
    await room.shutdown()


async def test_a_store_that_fails_still_lets_the_room_alert_out(clock: _Clock) -> None:
    room, row, lecturer, _ = await _silent_room(clock)
    log = room.alert_recorder = _AlertLog(fail=True)

    await _watch(room, row)

    assert log.calls == 1
    [raised] = lecturer.of(ServerEventType.ALERT_RAISED)
    assert raised["data"]["kind"] == "breakout_inactive"
    await room.shutdown()


async def test_a_room_nobody_has_been_heard_from_never_raises_an_alert(clock: _Clock) -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)

    clock.advance(3600)
    await _watch(room, row)

    assert lecturer.of(ServerEventType.ALERT_RAISED) == []
    assert room.rooms(row.session_id)[0].status is RoomStatus.UNKNOWN
    await room.shutdown()


# -- breakout rooms: joining, and consent -------------------------------------------------


async def test_a_lecturer_joining_mid_class_is_told_the_rooms_as_they_stand() -> None:
    room, events, row = await _class()
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student, "Room 1")
    await _record(room, row, student, _signal(speaking=True))
    lecturer = uuid4()

    staff_welcome = room.welcome(row.session_id, SessionStatus.ACTIVE, lecturer, Role.LECTURER)
    student_welcome = room.welcome(row.session_id, SessionStatus.ACTIVE, student, Role.STUDENT)

    [(_, told)] = [e for e in staff_welcome if e[0] is ServerEventType.ROOM_STATUS]
    assert (told["room_label"], told["status"], told["speaking_now"]) == ("Room 1", "active", 1)
    assert [e for e in student_welcome if e[0] is ServerEventType.ROOM_STATUS] == []
    await room.shutdown()


async def test_withdrawing_the_microphone_makes_the_room_unknown_but_keeps_the_member() -> None:
    room, events, row = await _class()
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)
    await _record(room, row, student, _signal(speaking=True))
    assert room.rooms(row.session_id)[0].status is RoomStatus.ACTIVE

    await room.withdraw_consent(student, MICROPHONE)

    [after] = room.rooms(row.session_id)
    assert (after.status, after.members, after.speaking_now) == (RoomStatus.UNKNOWN, 1, 0)
    await room.shutdown()


async def test_withdrawing_monitoring_makes_the_room_unknown_too() -> None:
    room, events, row = await _class()
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)
    await _record(room, row, student, _signal(speaking=True))

    await room.withdraw_consent(student, MONITORING)

    [after] = room.rooms(row.session_id)
    assert (after.status, after.members) == (RoomStatus.UNKNOWN, 1)
    await room.shutdown()


async def test_withdrawing_the_camera_leaves_what_the_room_heard() -> None:
    room, events, row = await _class()
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)
    await _record(room, row, student, _signal(gaze=0.5, speaking=True))

    await room.withdraw_consent(student, CAMERA)

    [after] = room.rooms(row.session_id)
    assert (after.status, after.speaking_now) == (RoomStatus.ACTIVE, 1)
    await room.shutdown()


# -- the watch's lifecycle ----------------------------------------------------------------


async def test_the_watch_starts_with_the_first_signal_and_not_before() -> None:
    room, events, row = await _class()
    live = room.get_running(row.session_id)
    assert live is not None and live.watch is None
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    _, declined = await join_as(events, row.session_id, Role.STUDENT)
    room.consents.set(declined, {TERMS})
    assert live.watch is None

    assert not await room.record_attention(row.session_id, declined, ATTENTIVE)
    assert live.watch is None
    await _record(room, row, student, ATTENTIVE)

    assert live.watch is not None and not live.watch.done()
    await room.shutdown()


async def test_the_watch_starts_with_the_first_confirmed_room_and_not_a_refused_one() -> None:
    room, events, row = await _class()
    live = room.get_running(row.session_id)
    assert live is not None
    _, student = await join_as(events, row.session_id, Role.STUDENT)

    assert await _confirm(room, row, student, "\x00") == ROOM_LABEL_INVALID
    assert live.watch is None
    assert await _confirm(room, row, student) is None

    assert live.watch is not None and not live.watch.done()
    await room.shutdown()


async def test_ending_the_session_cancels_the_watch() -> None:
    room, events, row = await _class()
    live = room.get_running(row.session_id)
    assert live is not None
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, ATTENTIVE)
    watch = live.watch
    assert watch is not None

    await room.end(row.session_id, SessionStatus.ENDED, 0)
    await asyncio.wait([watch], timeout=1)

    assert watch.cancelled()


async def test_shutting_down_cancels_the_watch() -> None:
    room, events, row = await _class()
    live = room.get_running(row.session_id)
    assert live is not None
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _confirm(room, row, student)
    watch = live.watch
    assert watch is not None and not watch.done()

    await room.shutdown()

    assert watch.cancelled()


async def test_the_timer_itself_runs_the_watch() -> None:
    room, events, row = await _class(watch=0.02)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, ATTENTIVE)
    assert room.engagement(row.session_id) == []

    await asyncio.sleep(0.1)

    assert [s.user_id for s in room.engagement(row.session_id)] == [student]
    await room.shutdown()


async def test_a_pass_that_fails_does_not_stop_the_next() -> None:
    room, events, row = await _class(watch=0.02)
    calls = []

    async def flaky(live: object) -> None:
        calls.append(live)
        if len(calls) == 1:
            raise RuntimeError("one bad pass")

    room.watch_once = flaky  # type: ignore[method-assign]
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    await _record(room, row, student, ATTENTIVE)

    await asyncio.sleep(0.15)

    assert len(calls) >= 2
    await room.shutdown()
