"""WebSocket handshake and protocol.

The hub itself is exercised directly rather than through a socket, so these run
without a server or a database.
"""

from uuid import uuid4

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

    async def send_json(
        self,
        payload: dict,
    ) -> None:
        if self.fail:
            raise ConnectionResetError("client gone")

        self.sent.append(payload)


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


async def test_user_channel_is_private() -> None:
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


async def test_user_channel_replays_progress_after_reconnect() -> None:
    hub = SessionHub()
    user_id = uuid4()

    for percent in (10, 40, 75):
        await hub.send_to_user_channel(
            user_id,
            ServerEventType.MATERIAL_PROGRESS,
            {"percent": percent},
        )

    socket = _FakeSocket()
    replayed, resumed_from = await hub.join_and_replay(
        Connection(socket, user_id, None),  # type: ignore[arg-type]
        last_seq=1,
    )

    assert replayed == 2
    assert resumed_from == 1
    assert [message["seq"] for message in socket.sent] == [2, 3]


async def test_user_channel_replay_is_bounded() -> None:
    hub = SessionHub()
    user_id = uuid4()

    for percent in range(MAX_REPLAY_EVENTS_PER_CHANNEL + 10):
        await hub.send_to_user_channel(
            user_id,
            ServerEventType.MATERIAL_PROGRESS,
            {"percent": percent},
        )

    socket = _FakeSocket()
    replayed, resumed_from = await hub.join_and_replay(
        Connection(socket, user_id, None),  # type: ignore[arg-type]
        last_seq=0,
    )

    assert replayed == MAX_REPLAY_EVENTS_PER_CHANNEL
    assert resumed_from == 0
    assert socket.sent[0]["seq"] == 11


async def test_replay_rejects_a_cursor_from_an_old_server_stream() -> None:
    hub = SessionHub()
    user_id = uuid4()
    socket = _FakeSocket()

    replayed, resumed_from = await hub.join_and_replay(
        Connection(socket, user_id, None),  # type: ignore[arg-type]
        last_seq=9,
    )

    assert replayed == 0
    assert resumed_from is None
    assert socket.sent == []


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
