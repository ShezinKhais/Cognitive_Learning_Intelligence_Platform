"""What the classroom hands its recorders: closes and the reveals they
return, attendance, and the startup check that each one is registered.

Owner: General CS. The recorders are fakes; test_live_store.py covers the
real ones against a database.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.realtime import recorders as recorders_module
from app.realtime.classroom import Classroom
from app.realtime.hub import Connection, SessionHub
from app.realtime.recorders import (
    Attendance,
    ClosedQuestion,
    Submission,
)
from app.schemas.events import (
    FeedbackResultPayload,
    ServerEventType,
)
from app.schemas.identity import Role
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


# -- closes and reveals -------------------------------------------------------


class _Closes:
    def __init__(self) -> None:
        self.closed: list[ClosedQuestion] = []
        self.release = asyncio.Event()
        self.release.set()

    async def record_close(self, closed: ClosedQuestion) -> dict:
        await self.release.wait()
        self.closed.append(closed)
        return {}


async def test_the_close_recorder_is_told_who_was_shown_and_who_answered() -> None:
    room, events = make_room(window=0.1)
    row = make_row()
    socket, answered = await join_as(events, row.session_id, Role.STUDENT)
    _, silent = await join_as(events, row.session_id, Role.STUDENT)
    closes = room.close_recorder = _Closes()
    question = await deliver_next(room, row)
    await room.submit(row.session_id, answered, Role.STUDENT, answer_to(question.question_id))

    await asyncio.sleep(0.25)

    [closed] = closes.closed
    assert (closed.question_id, closed.reason) == (question.question_id, "window_elapsed")
    assert closed.eligible == {answered, silent}
    assert closed.answered == {answered}
    assert socket.of(ServerEventType.QUESTION_CLOSED)
    await room.shutdown()


async def test_the_close_recorder_hears_about_a_question_the_end_closed() -> None:
    room, _ = make_room()
    row = make_row()
    closes = room.close_recorder = _Closes()
    question = await deliver_next(room, row)

    await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    [closed] = closes.closed
    assert (closed.question_id, closed.reason) == (question.question_id, "session_ended")


async def test_a_slow_close_recorder_does_not_hold_up_the_session() -> None:
    """It runs once the session's lock is released, so the next question can
    go out while the last close is still being stored."""
    room, _ = make_room(window=0.05)
    row = make_row()
    closes = room.close_recorder = _Closes()
    closes.release.clear()
    await deliver_next(room, row)
    await asyncio.sleep(0.15)

    await asyncio.wait_for(deliver_next(room, row), 1)

    assert closes.closed == []
    closes.release.set()
    await room.shutdown()


async def test_a_failing_close_recorder_is_logged_and_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, _ = make_room(window=0.05)
    row = make_row()

    class Broken:
        async def record_close(self, closed: ClosedQuestion) -> None:
            raise RuntimeError("database gone")

    room.close_recorder = Broken()
    await deliver_next(room, row)
    with caplog.at_level("ERROR", logger="clip.classroom"):
        await asyncio.sleep(0.15)

    assert "could not record a question close" in caplog.text
    await deliver_next(room, row)
    await room.shutdown()


class _Reveals:
    """Reveals the answer to everyone who answered, as AI 1's recorder does."""

    async def record_close(self, closed: ClosedQuestion) -> dict:
        return {
            user: FeedbackResultPayload(
                question_id=closed.question_id, correct=True, explanation="Jupiter."
            )
            for user in closed.answered
        }


async def test_the_answer_is_revealed_to_students_when_the_class_ends() -> None:
    """The end forgot the session before recording the close, so the reveal
    for the last question went to a stream nobody was in."""
    room, events = make_room()
    row = make_row()
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    room.close_recorder = _Reveals()
    question = await deliver_next(room, row)
    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))
    socket.sent.clear()

    await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    [reveal] = socket.of(ServerEventType.FEEDBACK_RESULT)
    assert reveal["data"]["question_id"] == str(question.question_id)
    assert events.tracked_stream_count() == 0


async def test_a_slow_socket_does_not_fail_the_close_it_reveals(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The reveal is sent after the recorder returns, outside its budget, so
    a stored close is not logged as a failure and nobody's reveal is cut off."""
    monkeypatch.setattr(recorders_module, "RECORD_TIMEOUT_SECONDS", 0.05)
    room, events = make_room()
    row = make_row()

    class Slow(FakeSocket):
        async def send_json(self, payload: dict) -> None:
            if payload["type"] == ServerEventType.FEEDBACK_RESULT.value:
                await asyncio.sleep(0.04)
            await super().send_json(payload)

    sockets = []
    for _ in range(3):
        socket, student = Slow(), uuid4()
        await events.join(Connection(socket, student, row.session_id, Role.STUDENT))  # type: ignore[arg-type]
        sockets.append((socket, student))
    room.close_recorder = _Reveals()
    question = await deliver_next(room, row)
    for _, student in sockets:
        await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))
    for socket, _ in sockets:
        socket.sent.clear()

    with caplog.at_level("ERROR", logger="clip.classroom"):
        await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    assert "could not record a question close" not in caplog.text
    assert all(len(socket.of(ServerEventType.FEEDBACK_RESULT)) == 1 for socket, _ in sockets)


# -- attendance --------------------------------------------------------------


class _Attendance:
    def __init__(self) -> None:
        self.joined: list[Attendance] = []
        self.left: list[Attendance] = []

    async def record_join(self, joined: Attendance) -> None:
        self.joined.append(joined)

    async def record_leave(self, left: Attendance) -> None:
        self.left.append(left)


async def _tab(events: SessionHub, session_id: UUID, user: UUID, role: Role) -> Connection:
    connection = Connection(FakeSocket(), user, session_id, role)  # type: ignore[arg-type]
    await events.join(connection)
    return connection


async def test_a_student_leaves_the_class_only_when_their_last_tab_closes() -> None:
    """The stored record counts joins, not open sockets, so it cannot tell a
    student who closed one of two tabs from one who left."""
    room, events = make_room()
    row = make_row()
    attendance = room.participant_recorder = _Attendance()
    student = uuid4()
    tabs = []
    for _ in range(2):
        tabs.append(await _tab(events, row.session_id, student, Role.STUDENT))
        await room.arrived(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert [a.user_id for a in attendance.joined] == [student, student]

    await events.leave(tabs[0])
    await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert attendance.left == []

    await events.leave(tabs[1])
    await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert [a.user_id for a in attendance.left] == [student]
    await room.shutdown()


async def test_staff_are_told_when_a_student_arrives_or_leaves_but_not_about_a_second_tab() -> None:
    """Presence changes with the student, not the socket: a second tab is
    attendance, and says nothing new about who is in the room."""
    room, events = make_room()
    row = make_row()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    student = uuid4()
    tabs = []
    for _ in range(2):
        tabs.append(await _tab(events, row.session_id, student, Role.STUDENT))
        await room.arrived(row.session_id, student, Role.STUDENT, SessionStatus.PREPARED)
    for tab in tabs:
        await events.leave(tab)
        await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.PREPARED)

    counts = [e["data"]["participant_count"] for e in lecturer.of(ServerEventType.SESSION_STATE)]
    assert counts == [1, 0]
    await room.shutdown()


async def test_staff_are_not_participants() -> None:
    """A lecturer is in the room without attending it, and the store keeps
    participants by student, which they have no row in."""
    room, events = make_room()
    row = make_row()
    attendance = room.participant_recorder = _Attendance()
    lecturer = uuid4()
    tab = await _tab(events, row.session_id, lecturer, Role.LECTURER)

    await room.arrived(row.session_id, lecturer, Role.LECTURER, SessionStatus.ACTIVE)
    await events.leave(tab)
    await room.departed(row.session_id, lecturer, Role.LECTURER, SessionStatus.ACTIVE)

    assert (attendance.joined, attendance.left) == ([], [])
    await room.shutdown()


async def test_a_failing_participant_recorder_is_logged_and_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, events = make_room()
    row = make_row()

    class Broken:
        async def record_join(self, joined: Attendance) -> None:
            raise RuntimeError("database gone")

        async def record_leave(self, left: Attendance) -> None:
            raise RuntimeError("database gone")

    room.participant_recorder = Broken()
    student = uuid4()
    tab = await _tab(events, row.session_id, student, Role.STUDENT)

    with caplog.at_level("ERROR", logger="clip.classroom"):
        await room.arrived(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)
        await events.leave(tab)
        await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert "could not record a student joining" in caplog.text
    assert "could not record a student leaving" in caplog.text
    await room.shutdown()


# -- startup wiring -------------------------------------------------------------


class _Recorder:
    async def record(self, submission: Submission) -> None:
        return None

    async def record_prompt(self, outcome) -> None:  # noqa: ANN001
        return None

    async def record_close(self, closed) -> dict:  # noqa: ANN001
        return {}

    async def record_join(self, joined) -> None:  # noqa: ANN001
        return None

    async def record_leave(self, left) -> None:  # noqa: ANN001
        return None


def _wired(room: Classroom) -> None:
    room.recorder = room.prompt_recorder = room.close_recorder = _Recorder()  # type: ignore[assignment]
    room.participant_recorder = _Recorder()  # type: ignore[assignment]


def test_development_is_told_what_live_sessions_will_not_store(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    room, _ = make_room()

    with caplog.at_level("WARNING", logger="clip.classroom"):
        room.check_wiring()

    assert "answers are not stored" in caplog.text
    assert "prompt outcomes are not stored" in caplog.text
    assert "question closes are not stored" in caplog.text
    assert "who attended is not stored" in caplog.text


def test_production_will_not_start_without_somewhere_to_store_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    room, _ = make_room(production=True)

    with pytest.raises(RuntimeError, match="answers are not stored"):
        room.check_wiring()

    _wired(room)
    room.check_wiring()


@pytest.mark.parametrize("workers", ["2", "4", "auto"])
def test_live_sessions_refuse_more_than_one_worker(
    monkeypatch: pytest.MonkeyPatch, workers: str
) -> None:
    """Each worker would restore the same session and run its own cycle."""
    monkeypatch.setenv("WEB_CONCURRENCY", workers)
    room, _ = make_room(production=True)
    _wired(room)

    with pytest.raises(RuntimeError, match="single worker"):
        room.check_wiring()


def test_one_worker_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    room, _ = make_room(production=True)
    _wired(room)

    room.check_wiring()
