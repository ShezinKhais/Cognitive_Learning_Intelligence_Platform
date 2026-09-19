"""The reconnect handshake: READY, the join, and replay of missed progress.

Owner: General CS. A lecturer's tab that drops and reconnects should pick up
where it left off when the server can prove it has everything since, and be
told to start afresh when it cannot.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.realtime.hub import MAX_REPLAY_EVENTS_PER_CHANNEL, Connection, SessionHub
from app.schemas.events import ServerEventType


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: tuple[int, str] | None = None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


class _StallsAfterReady(_FakeSocket):
    """Accepts READY, then stops acknowledging anything else."""

    async def send_json(self, payload: dict) -> None:
        if payload["type"] != ServerEventType.READY.value:
            await asyncio.sleep(3600)
        await super().send_json(payload)


async def _progress(hub: SessionHub, user_id: UUID, percent: int) -> None:
    await hub.send_to_user_channel(user_id, ServerEventType.MATERIAL_PROGRESS, {"percent": percent})


async def _first_visit(hub: SessionHub, user_id: UUID) -> tuple[Connection, UUID]:
    """A new workspace tab, and the stream generation READY told it."""
    socket = _FakeSocket()
    connection = Connection(socket, user_id, None)  # type: ignore[arg-type]
    assert await hub.connect(connection, last_seq=0)
    return connection, UUID(socket.sent[0]["data"]["stream_id"])


async def test_user_channel_replays_progress_after_reconnect() -> None:
    hub = SessionHub()
    user_id = uuid4()
    first, generation = await _first_visit(hub, user_id)
    await _progress(hub, user_id, 10)
    await hub.leave(first)
    for percent in (40, 75):
        await _progress(hub, user_id, percent)

    socket = _FakeSocket()
    assert await hub.connect(Connection(socket, user_id, None), 1, generation)  # type: ignore[arg-type]

    assert [message["type"] for message in socket.sent] == [
        "ready",
        "material.progress",
        "material.progress",
    ]
    assert socket.sent[0]["data"]["resumed_from_seq"] == 1
    assert socket.sent[0]["data"]["stream_id"] == str(generation)
    assert [message["seq"] for message in socket.sent[1:]] == [2, 3]


async def test_a_new_tab_receives_progress_sent_before_its_upload_answered() -> None:
    """A first visit asks for sequence zero, so progress the pipeline emitted
    before the 202 reached the browser is not lost."""
    hub = SessionHub()
    user_id = uuid4()
    await _progress(hub, user_id, 5)

    socket = _FakeSocket()
    assert await hub.connect(Connection(socket, user_id, None), last_seq=0)  # type: ignore[arg-type]

    assert [message["type"] for message in socket.sent] == ["ready", "material.progress"]
    assert socket.sent[0]["data"]["resumed_from_seq"] == 0


async def test_user_channel_replay_is_bounded() -> None:
    hub = SessionHub()
    user_id = uuid4()
    first, generation = await _first_visit(hub, user_id)
    await hub.leave(first)
    for percent in range(MAX_REPLAY_EVENTS_PER_CHANNEL + 10):
        await _progress(hub, user_id, percent)

    socket = _FakeSocket()
    assert await hub.connect(Connection(socket, user_id, None), 0, generation)  # type: ignore[arg-type]

    # Replaying only the retained tail would claim there was no gap.
    assert [message["type"] for message in socket.sent] == ["ready"]
    assert socket.sent[0]["data"]["resumed_from_seq"] is None
    assert socket.sent[0]["data"]["stream_id"] == str(generation)


async def test_replay_rejects_a_cursor_from_an_old_server_stream() -> None:
    """The new process has already reached the old cursor value. Sequence-only
    validation would accept it and silently skip the first nine new events."""
    hub = SessionHub()
    user_id = uuid4()
    for percent in range(10):
        await _progress(hub, user_id, percent)

    socket = _FakeSocket()
    assert await hub.connect(Connection(socket, user_id, None), 9, uuid4())  # type: ignore[arg-type]

    assert [message["type"] for message in socket.sent] == ["ready"]
    assert socket.sent[0]["data"]["resumed_from_seq"] is None
    assert socket.sent[0]["data"]["stream_id"] is not None


async def test_session_connection_has_only_the_session_sequence_stream() -> None:
    """One socket, one numbered stream: a session socket gets none of the
    user's material progress, and its cursor is the session's."""
    hub = SessionHub()
    user_id, session_id = uuid4(), uuid4()
    await _progress(hub, user_id, 25)

    socket = _FakeSocket()
    connection = Connection(socket, user_id, session_id)  # type: ignore[arg-type]
    assert await hub.connect(connection, last_seq=0)

    progress_delivered = await hub.send_to_user_channel(
        user_id, ServerEventType.MATERIAL_PROGRESS, {"percent": 50}
    )
    session_delivered = await hub.broadcast(session_id, ServerEventType.QUESTION_DELIVERED, {})

    assert progress_delivered == 0
    assert session_delivered == 1
    assert [message["type"] for message in socket.sent] == ["ready", "question.delivered"]
    assert socket.sent[0]["data"]["resumed_from_seq"] == 0
    assert socket.sent[0]["data"]["stream_id"] == str(hub._stream(session_id).generation)
    assert socket.sent[1]["seq"] == 1


async def test_a_session_reconnect_replays_what_it_missed() -> None:
    hub = SessionHub()
    student, session_id = uuid4(), uuid4()
    first = _FakeSocket()
    await hub.connect(Connection(first, student, session_id), last_seq=0)  # type: ignore[arg-type]
    await hub.broadcast(session_id, ServerEventType.QUESTION_DELIVERED, {"n": 1})
    stream_id = UUID(first.sent[0]["data"]["stream_id"])
    await hub.leave(next(iter(hub._streams[session_id].members)))

    await hub.broadcast(session_id, ServerEventType.QUESTION_CLOSED, {"n": 1})
    await hub.broadcast(session_id, ServerEventType.QUESTION_DELIVERED, {"n": 2})

    again = _FakeSocket()
    connection = Connection(again, student, session_id)  # type: ignore[arg-type]
    assert await hub.connect(connection, last_seq=1, generation=stream_id)

    assert again.sent[0]["data"]["resumed_from_seq"] == 1
    assert [(m["type"], m["seq"]) for m in again.sent[1:]] == [
        ("question.closed", 2),
        ("question.delivered", 3),
    ]


async def test_private_events_do_not_open_a_gap_for_anyone_else() -> None:
    """A receipt for one student is outside the session's numbering, so the
    rest of the class sees consecutive seqs."""
    hub = SessionHub()
    session_id, answering = uuid4(), uuid4()
    bystander = _FakeSocket()
    await hub.join(Connection(bystander, uuid4(), session_id))  # type: ignore[arg-type]
    private = _FakeSocket()
    await hub.join(Connection(private, answering, session_id))  # type: ignore[arg-type]

    await hub.broadcast(session_id, ServerEventType.QUESTION_DELIVERED, {})
    await hub.send_to_user(session_id, answering, ServerEventType.ANSWER_RECEIPT, {})
    await hub.broadcast(session_id, ServerEventType.QUESTION_CLOSED, {})

    assert [m["seq"] for m in bystander.sent] == [1, 2]
    assert [m["seq"] for m in private.sent] == [1, 0, 2]


async def test_the_welcome_follows_ready_and_replay() -> None:
    hub = SessionHub()
    session_id = uuid4()
    await hub.broadcast(session_id, ServerEventType.QUESTION_DELIVERED, {})
    socket = _FakeSocket()

    async def welcome() -> list[tuple[ServerEventType, dict]]:
        return [(ServerEventType.SESSION_STATE, {"status": "active"})]

    connection = Connection(socket, uuid4(), session_id)  # type: ignore[arg-type]
    assert await hub.connect(connection, last_seq=0, welcome=welcome)

    assert [(m["type"], m["seq"]) for m in socket.sent] == [
        ("ready", 0),
        ("question.delivered", 1),
        ("session.state", 0),
    ]


async def test_a_stalled_replay_send_releases_the_delivery_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.realtime.hub.SEND_TIMEOUT_SECONDS", 0.01)
    hub = SessionHub()
    user_id = uuid4()
    await _progress(hub, user_id, 25)

    stalled = _StallsAfterReady()
    assert await asyncio.wait_for(
        hub.connect(Connection(stalled, user_id, None), last_seq=0),  # type: ignore[arg-type]
        timeout=0.5,
    )

    healthy = _FakeSocket()
    await hub.join(Connection(healthy, user_id, None))  # type: ignore[arg-type]
    delivered = await asyncio.wait_for(
        hub.send_to_user_channel(user_id, ServerEventType.MATERIAL_PROGRESS, {}),
        timeout=0.1,
    )
    assert delivered == 1


async def test_a_ready_that_cannot_be_delivered_joins_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.realtime.hub.SEND_TIMEOUT_SECONDS", 0.01)

    class NeverAcknowledges(_FakeSocket):
        async def send_json(self, payload: dict) -> None:
            await asyncio.sleep(3600)

    hub = SessionHub()
    user_id = uuid4()

    joined = await hub.connect(Connection(NeverAcknowledges(), user_id, None))  # type: ignore[arg-type]

    assert joined is False
    assert await hub.send_to_user_channel(user_id, ServerEventType.MATERIAL_PROGRESS, {}) == 0
