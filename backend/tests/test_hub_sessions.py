"""Session rooms on the hub: broadcast, targeted delivery and sequencing.

Owner: General CS. The user-channel side is in test_hub_channels.py and the
reconnect handshake in test_hub_replay.py; test_ws.py covers the endpoint.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.realtime.hub import MAX_TRACKED_STREAMS, Connection, SessionHub
from app.schemas.events import ServerEventType
from app.schemas.identity import Role


class _FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionResetError("client gone")
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        return None


async def _student(hub: SessionHub, session: UUID, student: UUID | None = None) -> _FakeSocket:
    socket = _FakeSocket()
    await hub.join(Connection(socket, student or uuid4(), session))  # type: ignore[arg-type]
    return socket


def _seqs(socket: _FakeSocket) -> list[int]:
    return [frame["seq"] for frame in socket.sent]


async def test_sequence_numbers_increase_per_session() -> None:
    """Clients detect dropped messages by watching for a seq gap."""
    hub = SessionHub()
    session, other = uuid4(), uuid4()
    in_session = await _student(hub, session)
    in_other = await _student(hub, other)

    for _ in range(3):
        await hub.broadcast(session, ServerEventType.PONG, {})
    await hub.broadcast(other, ServerEventType.PONG, {})

    assert _seqs(in_session) == [1, 2, 3]
    assert _seqs(in_other) == [1]


async def test_broadcast_reaches_everyone_in_the_room() -> None:
    hub = SessionHub()
    session = uuid4()
    sockets = [await _student(hub, session) for _ in range(3)]

    delivered = await hub.broadcast(session, ServerEventType.SESSION_STATE, {"status": "active"})

    assert delivered == 3
    assert hub.participant_count(session) == 3
    assert all(socket.sent[0]["type"] == "session.state" for socket in sockets)


async def test_one_dead_connection_does_not_stop_the_broadcast() -> None:
    """One disconnected student must not stop delivery to others."""
    hub = SessionHub()
    session = uuid4()
    await _student(hub, session)
    await hub.join(Connection(_FakeSocket(fail=True), uuid4(), session))  # type: ignore[arg-type]

    delivered = await hub.broadcast(session, ServerEventType.QUESTION_DELIVERED, {})

    assert delivered == 1
    assert hub.participant_count(session) == 1


async def test_targeted_send_is_private() -> None:
    """Attention prompts must only reach the intended student."""
    hub = SessionHub()
    session, target_id = uuid4(), uuid4()
    target = await _student(hub, session, target_id)
    bystander = await _student(hub, session)

    sent = await hub.send_to_user(session, target_id, ServerEventType.PROMPT_ATTENTION, {})

    assert sent is True
    assert len(target.sent) == 1
    assert bystander.sent == []


async def test_targeted_send_reaches_every_connection_a_student_holds() -> None:
    """A student may have both a desktop and browser connection."""
    hub = SessionHub()
    session, student = uuid4(), uuid4()
    desktop = await _student(hub, session, student)
    browser = await _student(hub, session, student)

    sent = await hub.send_to_user(session, student, ServerEventType.PROMPT_ATTENTION, {})

    assert sent is True
    assert len(desktop.sent) == 1
    assert len(browser.sent) == 1


async def test_targeted_send_reports_failure_when_only_socket_is_dead() -> None:
    hub = SessionHub()
    session, student = uuid4(), uuid4()
    await hub.join(Connection(_FakeSocket(fail=True), student, session))  # type: ignore[arg-type]

    sent = await hub.send_to_user(session, student, ServerEventType.PROMPT_ATTENTION, {})

    assert sent is False
    assert hub.participant_count(session) == 0


async def test_an_emptied_room_keeps_its_sequence_counter() -> None:
    """Temporary disconnects must not reset a session sequence."""
    hub = SessionHub()
    session = uuid4()
    connection = Connection(_FakeSocket(), uuid4(), session)  # type: ignore[arg-type]
    await hub.join(connection)
    for _ in range(2):
        await hub.broadcast(session, ServerEventType.PONG, {})

    await hub.leave(connection)
    assert hub.participant_count(session) == 0

    returning = await _student(hub, session)
    await hub.broadcast(session, ServerEventType.PONG, {})
    assert _seqs(returning) == [3]


async def test_forget_session_clears_the_counter() -> None:
    """The session-end hook may reset state after a session ends."""
    hub = SessionHub()
    session = uuid4()
    await hub.broadcast(session, ServerEventType.PONG, {})

    hub.forget_session(session)

    socket = await _student(hub, session)
    await hub.broadcast(session, ServerEventType.PONG, {})
    assert _seqs(socket) == [1]


async def test_sequence_counters_stop_growing_at_the_ceiling() -> None:
    """Idle session counters must remain bounded."""
    hub = SessionHub()

    for _ in range(MAX_TRACKED_STREAMS + 50):
        await hub.broadcast(uuid4(), ServerEventType.PONG, {})

    assert hub.tracked_stream_count() <= MAX_TRACKED_STREAMS


async def test_a_live_session_keeps_its_counter_when_the_ceiling_is_reached() -> None:
    """A live session must not lose its sequence counter."""
    hub = SessionHub()
    live = uuid4()
    socket = await _student(hub, live)
    await hub.broadcast(live, ServerEventType.PONG, {})

    for _ in range(MAX_TRACKED_STREAMS + 50):
        await hub.broadcast(uuid4(), ServerEventType.PONG, {})
    await hub.broadcast(live, ServerEventType.PONG, {})

    assert _seqs(socket) == [1, 2]


async def test_leaving_empties_the_room() -> None:
    hub = SessionHub()
    session = uuid4()
    connection = Connection(_FakeSocket(), uuid4(), session)  # type: ignore[arg-type]

    await hub.join(connection)
    assert hub.participant_count(session) == 1

    await hub.leave(connection)
    assert hub.participant_count(session) == 0


async def test_staff_and_students_in_a_session_are_told_apart() -> None:
    """The lecturer panel's student count, and anything sent to staff alone,
    depend on this split."""
    hub = SessionHub()
    session, elsewhere = uuid4(), uuid4()
    lecturer, admin, student = uuid4(), uuid4(), uuid4()
    for user, role, room in (
        (lecturer, Role.LECTURER, session),
        (admin, Role.ADMIN, session),
        (student, Role.STUDENT, session),
        (uuid4(), Role.LECTURER, elsewhere),
    ):
        await hub.join(Connection(_FakeSocket(), user, room, role))  # type: ignore[arg-type]

    assert hub.staff_ids(session) == {lecturer, admin}
    assert hub.student_ids(session) == {student}
    assert hub.staff_ids(uuid4()) == set()
