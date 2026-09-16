"""WebSocket handshake and protocol.

The hub itself is exercised directly rather than through a socket, so these run
without a server or a database.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.realtime.hub import (
    MAX_REPLAY_EVENTS_PER_CHANNEL,
    MAX_TRACKED_SESSIONS,
    Connection,
    SessionHub,
)
from app.schemas.events import (
    ClientEventType,
    ServerEventType,
)

from .dev_credentials import STUDENT_PASSWORD


def test_socket_rejects_a_non_auth_first_event(
    client: TestClient,
) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": ClientEventType.PING.value,
                    "data": {},
                }
            )
            ws.receive_json()

    assert exc.value.code == 4001


def test_socket_rejects_a_malformed_event(
    client: TestClient,
) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": "not-a-real-event",
                }
            )
            ws.receive_json()

    assert exc.value.code == 4400


def test_socket_rejects_an_invalid_token(
    client: TestClient,
) -> None:
    """A malformed or untrusted token closes with the auth code."""
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": ClientEventType.AUTH.value,
                    "data": {
                        "token": "anything",
                    },
                }
            )
            ws.receive_json()

    assert exc.value.code == 4001


def test_socket_accepts_a_valid_token(
    client: TestClient,
) -> None:
    """A valid token can authenticate without requesting a session."""
    from app.auth.store import STUDENT_ID

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "student@clip.example.com",
            "password": STUDENT_PASSWORD,
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json(
            {
                "type": ClientEventType.AUTH.value,
                "data": {
                    "token": token,
                    "last_seq": 0,
                },
            }
        )

        ready = ws.receive_json()

    assert ready["type"] == "ready"
    assert ready["data"]["user_id"] == str(STUDENT_ID)
    assert ready["data"]["session_id"] is None
    assert ready["data"]["resumed_from_seq"] == 0
    assert UUID(ready["data"]["stream_id"])


def test_socket_rejects_unverified_session_membership(
    client: TestClient,
) -> None:
    """A valid token does not authorize an arbitrary session."""
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "student@clip.example.com",
            "password": STUDENT_PASSWORD,
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]
    session_id = uuid4()

    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": ClientEventType.AUTH.value,
                    "data": {
                        "token": token,
                        "session_id": str(session_id),
                    },
                }
            )
            ws.receive_json()

    assert exc.value.code == 4003


def test_socket_rejects_a_malformed_auth_payload(
    client: TestClient,
) -> None:
    """An auth event missing its token is malformed."""
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": ClientEventType.AUTH.value,
                    "data": {},
                }
            )
            ws.receive_json()

    assert exc.value.code == 4400


@pytest.mark.parametrize(
    ("label", "send"),
    [
        (
            "json array",
            lambda ws: ws.send_json(["hello"]),
        ),
        (
            "json string",
            lambda ws: ws.send_json("hello"),
        ),
        (
            "json null",
            lambda ws: ws.send_json(None),
        ),
        (
            "not json",
            lambda ws: ws.send_text("<html>"),
        ),
        (
            "binary frame",
            lambda ws: ws.send_bytes(b"\x00\x01"),
        ),
    ],
)
def test_a_first_frame_that_is_not_a_json_object_closes_cleanly(
    client: TestClient,
    label: str,
    send,
) -> None:
    """Invalid first frames must close cleanly rather than fault."""
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            send(ws)
            ws.receive_json()

    assert exc.value.code == 4400, label


class _FakeSocket:
    def __init__(
        self,
        fail: bool = False,
    ) -> None:
        self.sent: list[dict] = []
        self.fail = fail
        self.closed: tuple[int, str] | None = None

    async def send_json(
        self,
        payload: dict,
    ) -> None:
        if self.fail:
            raise ConnectionResetError("client gone")

        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)

    async def send_ready(
        self,
        resumed_from_seq: int | None,
        stream_id: UUID | None,
    ) -> None:
        await self.send_json(
            {
                "type": ServerEventType.READY.value,
                "seq": 0,
                "data": {
                    "resumed_from_seq": resumed_from_seq,
                    "stream_id": str(stream_id) if stream_id else None,
                },
            }
        )


class _BlockingSocket(_FakeSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send_json(self, payload: dict) -> None:
        self.send_started.set()
        await self.release_send.wait()
        await super().send_json(payload)


class _ReplayBlockingSocket(_BlockingSocket):
    async def send_ready(
        self,
        resumed_from_seq: int | None,
        stream_id: UUID | None,
    ) -> None:
        await _FakeSocket.send_json(
            self,
            {
                "type": ServerEventType.READY.value,
                "seq": 0,
                "data": {
                    "resumed_from_seq": resumed_from_seq,
                    "stream_id": str(stream_id) if stream_id else None,
                },
            },
        )


async def test_sequence_numbers_increase_per_session() -> None:
    """Clients detect dropped messages by watching for a seq gap."""
    hub = SessionHub()
    session = uuid4()

    seqs = [
        hub.build(
            session,
            ServerEventType.PONG,
            {},
        ).seq
        for _ in range(3)
    ]

    assert seqs == [1, 2, 3]

    other = uuid4()

    assert (
        hub.build(
            other,
            ServerEventType.PONG,
            {},
        ).seq
        == 1
    )


async def test_broadcast_reaches_everyone_in_the_room() -> None:
    hub = SessionHub()
    session = uuid4()

    sockets = [_FakeSocket() for _ in range(3)]

    for socket in sockets:
        await hub.join(
            Connection(
                socket,
                uuid4(),
                session,
            )
        )  # type: ignore[arg-type]

    delivered = await hub.broadcast(
        session,
        ServerEventType.SESSION_STATE,
        {
            "status": "active",
        },
    )

    assert delivered == 3
    assert hub.participant_count(session) == 3

    for socket in sockets:
        assert socket.sent[0]["type"] == "session.state"


async def test_one_dead_connection_does_not_stop_the_broadcast() -> None:
    """One disconnected student must not stop delivery to others."""
    hub = SessionHub()
    session = uuid4()

    good = _FakeSocket()
    dead = _FakeSocket(fail=True)

    await hub.join(
        Connection(
            good,
            uuid4(),
            session,
        )
    )  # type: ignore[arg-type]

    await hub.join(
        Connection(
            dead,
            uuid4(),
            session,
        )
    )  # type: ignore[arg-type]

    delivered = await hub.broadcast(
        session,
        ServerEventType.QUESTION_DELIVERED,
        {},
    )

    assert delivered == 1
    assert hub.participant_count(session) == 1


async def test_user_channel_reaches_connections_without_a_session() -> None:
    """Material progress is addressed by the authenticated uploader id."""
    hub = SessionHub()
    user_id = uuid4()
    socket = _FakeSocket()

    await hub.join(
        Connection(
            socket,
            user_id,
            None,
        )
    )  # type: ignore[arg-type]

    delivered = await hub.send_to_user_channel(
        user_id,
        ServerEventType.MATERIAL_PROGRESS,
        {
            "material_id": str(uuid4()),
            "stage": "extracting",
            "percent": 25,
            "message": None,
        },
    )

    assert delivered == 1
    assert socket.sent[0]["type"] == "material.progress"
    assert socket.sent[0]["seq"] == 1


async def test_user_channel_is_private_to_the_authenticated_user() -> None:
    hub = SessionHub()
    target_id = uuid4()
    target = _FakeSocket()
    bystander = _FakeSocket()
    session_socket = _FakeSocket()

    await hub.join(Connection(target, target_id, None))  # type: ignore[arg-type]
    await hub.join(Connection(bystander, uuid4(), None))  # type: ignore[arg-type]
    await hub.join(
        Connection(session_socket, target_id, uuid4())  # type: ignore[arg-type]
    )

    delivered = await hub.send_to_user_channel(
        target_id,
        ServerEventType.MATERIAL_PROGRESS,
        {},
    )

    assert delivered == 1
    assert len(target.sent) == 1
    assert bystander.sent == []
    assert session_socket.sent == []


async def test_a_slow_user_channel_does_not_block_another_user() -> None:
    hub = SessionHub()
    slow_user = uuid4()
    fast_user = uuid4()
    slow_socket = _BlockingSocket()
    fast_socket = _FakeSocket()

    await hub.join(Connection(slow_socket, slow_user, None))  # type: ignore[arg-type]
    await hub.join(Connection(fast_socket, fast_user, None))  # type: ignore[arg-type]

    slow_delivery = asyncio.create_task(
        hub.send_to_user_channel(slow_user, ServerEventType.MATERIAL_PROGRESS, {})
    )
    await slow_socket.send_started.wait()

    try:
        fast_delivered = await asyncio.wait_for(
            hub.send_to_user_channel(fast_user, ServerEventType.MATERIAL_PROGRESS, {}),
            timeout=0.5,
        )
    finally:
        slow_socket.release_send.set()
        slow_delivered = await slow_delivery

    assert fast_delivered == 1
    assert slow_delivered == 1


async def test_a_stalled_socket_is_dropped_without_blocking_the_same_user(
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.realtime.hub.SEND_TIMEOUT_SECONDS", 0.01)
    hub = SessionHub()
    user_id = uuid4()
    stalled = _BlockingSocket()
    healthy = _FakeSocket()

    await hub.join(Connection(stalled, user_id, None))  # type: ignore[arg-type]
    await hub.join(Connection(healthy, user_id, None))  # type: ignore[arg-type]

    delivered = await asyncio.wait_for(
        hub.send_to_user_channel(user_id, ServerEventType.MATERIAL_PROGRESS, {}),
        timeout=0.5,
    )

    assert delivered == 1
    assert len(healthy.sent) == 1
    assert stalled.closed is not None

    # The timed-out connection was removed, so later progress does not wait
    # through another timeout before reaching the healthy tab.
    delivered_again = await asyncio.wait_for(
        hub.send_to_user_channel(user_id, ServerEventType.MATERIAL_PROGRESS, {}),
        timeout=0.1,
    )
    assert delivered_again == 1


async def test_a_stalled_replay_send_releases_the_user_delivery_lock(
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.realtime.hub.SEND_TIMEOUT_SECONDS", 0.01)
    hub = SessionHub()
    user_id = uuid4()
    await hub.send_to_user_channel(
        user_id,
        ServerEventType.MATERIAL_PROGRESS,
        {"percent": 25},
    )

    stalled = _ReplayBlockingSocket()
    joined = await asyncio.wait_for(
        hub.join_and_replay(
            Connection(stalled, user_id, None),  # type: ignore[arg-type]
            last_seq=0,
            stream_id=None,
            send_ready=stalled.send_ready,
        ),
        timeout=0.5,
    )

    assert joined == (0, 0)
    assert stalled.closed is not None

    healthy = _FakeSocket()
    await hub.join(Connection(healthy, user_id, None))  # type: ignore[arg-type]
    delivered = await asyncio.wait_for(
        hub.send_to_user_channel(user_id, ServerEventType.MATERIAL_PROGRESS, {}),
        timeout=0.1,
    )
    assert delivered == 1


async def test_user_channel_replays_progress_after_reconnect() -> None:
    hub = SessionHub()
    user_id = uuid4()

    first_socket = _FakeSocket()
    first_connection = Connection(first_socket, user_id, None)  # type: ignore[arg-type]
    first_join = await hub.join_and_replay(
        first_connection,
        last_seq=0,
        stream_id=None,
        send_ready=first_socket.send_ready,
    )
    assert first_join == (0, 0)

    await hub.send_to_user_channel(
        user_id,
        ServerEventType.MATERIAL_PROGRESS,
        {"percent": 10},
    )
    await hub.leave(first_connection)

    for percent in (40, 75):
        await hub.send_to_user_channel(
            user_id,
            ServerEventType.MATERIAL_PROGRESS,
            {"percent": percent},
        )

    stream_id = UUID(first_socket.sent[0]["data"]["stream_id"])
    socket = _FakeSocket()
    joined = await hub.join_and_replay(
        Connection(socket, user_id, None),  # type: ignore[arg-type]
        last_seq=1,
        stream_id=stream_id,
        send_ready=socket.send_ready,
    )
    assert joined is not None
    replayed, resumed_from = joined

    assert replayed == 2
    assert resumed_from == 1
    assert [message["type"] for message in socket.sent] == [
        "ready",
        "material.progress",
        "material.progress",
    ]
    assert socket.sent[0]["data"]["resumed_from_seq"] == 1
    assert socket.sent[0]["data"]["stream_id"] == str(stream_id)
    assert [message["seq"] for message in socket.sent[1:]] == [2, 3]


async def test_user_channel_replay_is_bounded() -> None:
    hub = SessionHub()
    user_id = uuid4()

    first_socket = _FakeSocket()
    first_connection = Connection(first_socket, user_id, None)  # type: ignore[arg-type]
    await hub.join_and_replay(
        first_connection,
        last_seq=0,
        stream_id=None,
        send_ready=first_socket.send_ready,
    )
    await hub.leave(first_connection)
    stream_id = UUID(first_socket.sent[0]["data"]["stream_id"])

    for percent in range(MAX_REPLAY_EVENTS_PER_CHANNEL + 10):
        await hub.send_to_user_channel(
            user_id,
            ServerEventType.MATERIAL_PROGRESS,
            {"percent": percent},
        )

    socket = _FakeSocket()
    joined = await hub.join_and_replay(
        Connection(socket, user_id, None),  # type: ignore[arg-type]
        last_seq=0,
        stream_id=stream_id,
        send_ready=socket.send_ready,
    )
    assert joined is not None
    replayed, resumed_from = joined

    assert replayed == 0
    assert resumed_from is None
    assert socket.sent == [
        {
            "type": "ready",
            "seq": 0,
            "data": {
                "resumed_from_seq": None,
                "stream_id": str(stream_id),
            },
        }
    ]


async def test_replay_rejects_a_cursor_from_an_old_server_stream() -> None:
    hub = SessionHub()
    user_id = uuid4()

    # The new process has already reached the old cursor value. Sequence-only
    # validation would accept this and silently skip the first nine new events.
    for percent in range(10):
        await hub.send_to_user_channel(
            user_id,
            ServerEventType.MATERIAL_PROGRESS,
            {"percent": percent},
        )

    socket = _FakeSocket()

    joined = await hub.join_and_replay(
        Connection(socket, user_id, None),  # type: ignore[arg-type]
        last_seq=9,
        stream_id=uuid4(),
        send_ready=socket.send_ready,
    )
    assert joined is not None
    replayed, resumed_from = joined

    assert replayed == 0
    assert resumed_from is None
    assert socket.sent[0]["type"] == "ready"
    assert socket.sent[0]["data"]["resumed_from_seq"] is None
    assert socket.sent[0]["data"]["stream_id"] is not None


async def test_session_connection_has_only_the_session_sequence_stream() -> None:
    hub = SessionHub()
    user_id = uuid4()
    session_id = uuid4()

    await hub.send_to_user_channel(
        user_id,
        ServerEventType.MATERIAL_PROGRESS,
        {"percent": 25},
    )

    socket = _FakeSocket()
    connection = Connection(socket, user_id, session_id)  # type: ignore[arg-type]
    joined = await hub.join_and_replay(
        connection,
        last_seq=0,
        stream_id=None,
        send_ready=socket.send_ready,
    )
    assert joined is not None
    replayed, resumed_from = joined
    progress_delivered = await hub.send_to_user_channel(
        user_id,
        ServerEventType.MATERIAL_PROGRESS,
        {"percent": 50},
    )
    session_delivered = await hub.broadcast(
        session_id,
        ServerEventType.QUESTION_DELIVERED,
        {},
    )

    assert replayed == 0
    assert resumed_from is None
    assert progress_delivered == 0
    assert session_delivered == 1
    assert [message["type"] for message in socket.sent] == [
        "ready",
        "question.delivered",
    ]
    assert socket.sent[0]["data"] == {
        "resumed_from_seq": None,
        "stream_id": None,
    }
    assert socket.sent[1]["seq"] == 1


async def test_targeted_send_is_private() -> None:
    """Attention prompts must only reach the intended student."""
    hub = SessionHub()
    session = uuid4()
    target_id = uuid4()

    target = _FakeSocket()
    bystander = _FakeSocket()

    await hub.join(
        Connection(
            target,
            target_id,
            session,
        )
    )  # type: ignore[arg-type]

    await hub.join(
        Connection(
            bystander,
            uuid4(),
            session,
        )
    )  # type: ignore[arg-type]

    sent = await hub.send_to_user(
        session,
        target_id,
        ServerEventType.PROMPT_ATTENTION,
        {},
    )

    assert sent is True
    assert len(target.sent) == 1
    assert bystander.sent == []


async def test_targeted_send_reaches_every_connection_a_student_holds() -> None:
    """A student may have both a desktop and browser connection."""
    hub = SessionHub()
    session = uuid4()
    student = uuid4()

    desktop = _FakeSocket()
    browser = _FakeSocket()

    await hub.join(
        Connection(
            desktop,
            student,
            session,
        )
    )  # type: ignore[arg-type]

    await hub.join(
        Connection(
            browser,
            student,
            session,
        )
    )  # type: ignore[arg-type]

    sent = await hub.send_to_user(
        session,
        student,
        ServerEventType.PROMPT_ATTENTION,
        {},
    )

    assert sent is True
    assert len(desktop.sent) == 1
    assert len(browser.sent) == 1


async def test_targeted_send_reports_failure_when_only_socket_is_dead() -> None:
    hub = SessionHub()
    session = uuid4()
    student = uuid4()

    await hub.join(
        Connection(
            _FakeSocket(fail=True),
            student,
            session,
        )
    )  # type: ignore[arg-type]

    sent = await hub.send_to_user(
        session,
        student,
        ServerEventType.PROMPT_ATTENTION,
        {},
    )

    assert sent is False
    assert hub.participant_count(session) == 0


async def test_an_emptied_room_keeps_its_sequence_counter() -> None:
    """Temporary disconnects must not reset a session sequence."""
    hub = SessionHub()
    session = uuid4()

    connection = Connection(
        _FakeSocket(),
        uuid4(),
        session,
    )  # type: ignore[arg-type]

    await hub.join(connection)

    hub.build(
        session,
        ServerEventType.PONG,
        {},
    )

    hub.build(
        session,
        ServerEventType.PONG,
        {},
    )

    await hub.leave(connection)

    assert hub.participant_count(session) == 0

    assert (
        hub.build(
            session,
            ServerEventType.PONG,
            {},
        ).seq
        == 3
    )


async def test_forget_session_clears_the_counter() -> None:
    """The session-end hook may reset state after a session ends."""
    hub = SessionHub()
    session = uuid4()

    hub.build(
        session,
        ServerEventType.PONG,
        {},
    )

    hub.forget_session(session)

    assert (
        hub.build(
            session,
            ServerEventType.PONG,
            {},
        ).seq
        == 1
    )


async def test_sequence_counters_stop_growing_at_the_ceiling() -> None:
    """Idle session counters must remain bounded."""
    hub = SessionHub()

    for _ in range(MAX_TRACKED_SESSIONS + 50):
        hub.build(
            uuid4(),
            ServerEventType.PONG,
            {},
        )

    assert hub.tracked_session_count() <= MAX_TRACKED_SESSIONS


async def test_a_live_session_keeps_its_counter_when_the_ceiling_is_reached() -> None:
    """A live session must not lose its sequence counter."""
    hub = SessionHub()
    live = uuid4()

    await hub.join(
        Connection(
            _FakeSocket(),
            uuid4(),
            live,
        )
    )  # type: ignore[arg-type]

    assert (
        hub.build(
            live,
            ServerEventType.PONG,
            {},
        ).seq
        == 1
    )

    for _ in range(MAX_TRACKED_SESSIONS + 50):
        hub.build(
            uuid4(),
            ServerEventType.PONG,
            {},
        )

    assert (
        hub.build(
            live,
            ServerEventType.PONG,
            {},
        ).seq
        == 2
    )


async def test_leaving_empties_the_room() -> None:
    hub = SessionHub()
    session = uuid4()

    connection = Connection(
        _FakeSocket(),
        uuid4(),
        session,
    )  # type: ignore[arg-type]

    await hub.join(connection)

    assert hub.participant_count(session) == 1

    await hub.leave(connection)

    assert hub.participant_count(session) == 0
