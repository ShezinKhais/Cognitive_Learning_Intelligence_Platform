"""WebSocket handshake and protocol.

The hub itself is exercised directly rather than through a socket, so these run
without a server or a database.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.realtime.hub import Connection, SessionHub
from app.schemas.events import ClientEventType, ServerEventType
from tests.dev_credentials import STUDENT_PASSWORD


def test_socket_rejects_a_non_auth_first_event(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": ClientEventType.PING.value, "data": {}})
            ws.receive_json()
    assert exc.value.code == 4001


def test_socket_rejects_a_malformed_event(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "not-a-real-event"})
            ws.receive_json()
    assert exc.value.code == 4400


def test_socket_rejects_an_invalid_token(client: TestClient) -> None:
    """A malformed or untrusted token closes with the authentication code."""
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": ClientEventType.AUTH.value, "data": {"token": "anything"}})
            ws.receive_json()
    assert exc.value.code == 4001




def test_socket_accepts_a_valid_token(client: TestClient) -> None:
    from app.auth.store import STUDENT_ID

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "student@clip.example.com", "password": STUDENT_PASSWORD},
    )
    token = login.json()["access_token"]

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": ClientEventType.AUTH.value, "data": {"token": token}})
        ready = ws.receive_json()

    assert ready["type"] == "ready"
    assert ready["data"]["user_id"] == str(STUDENT_ID)
    assert ready["data"]["session_id"] is None


def test_socket_rejects_a_malformed_auth_payload(client: TestClient) -> None:
    """An auth event missing its token is malformed, not merely unauthorised."""
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": ClientEventType.AUTH.value, "data": {}})
            ws.receive_json()
    assert exc.value.code == 4400


@pytest.mark.parametrize(
    ("label", "send"),
    [
        ("json array", lambda ws: ws.send_json(["hello"])),
        ("json string", lambda ws: ws.send_json("hello")),
        ("json null", lambda ws: ws.send_json(None)),
        ("not json", lambda ws: ws.send_text("<html>")),
        ("binary frame", lambda ws: ws.send_bytes(b"\x00\x01")),
    ],
)
def test_a_first_frame_that_is_not_a_json_object_closes_cleanly(
    client: TestClient, label: str, send
) -> None:
    """None of these may reach the handler as a server fault.

    Each one used to escape uncaught: AttributeError on the array, string and
    null, JSONDecodeError on the text, KeyError on the binary frame. Any
    unauthenticated caller could raise an exception inside the handler with a
    single frame. They are protocol errors and close 4400 like any other.
    """
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            send(ws)
            ws.receive_json()
    assert exc.value.code == 4400, label


class _FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionResetError("client gone")
        self.sent.append(payload)


async def test_sequence_numbers_increase_per_session() -> None:
    """Clients detect dropped messages by watching for a gap in seq."""
    hub = SessionHub()
    session = uuid4()

    seqs = [hub.build(session, ServerEventType.PONG, {}).seq for _ in range(3)]
    assert seqs == [1, 2, 3]

    other = uuid4()
    assert hub.build(other, ServerEventType.PONG, {}).seq == 1


async def test_broadcast_reaches_everyone_in_the_room() -> None:
    hub = SessionHub()
    session = uuid4()
    sockets = [_FakeSocket() for _ in range(3)]
    for socket in sockets:
        await hub.join(Connection(socket, uuid4(), session))  # type: ignore[arg-type]

    delivered = await hub.broadcast(session, ServerEventType.SESSION_STATE, {"status": "active"})

    assert delivered == 3
    assert hub.participant_count(session) == 3
    for socket in sockets:
        assert socket.sent[0]["type"] == "session.state"


async def test_one_dead_connection_does_not_stop_the_broadcast() -> None:
    """A student losing wifi must not prevent the other 39 getting a question."""
    hub = SessionHub()
    session = uuid4()
    good, dead = _FakeSocket(), _FakeSocket(fail=True)
    await hub.join(Connection(good, uuid4(), session))  # type: ignore[arg-type]
    await hub.join(Connection(dead, uuid4(), session))  # type: ignore[arg-type]

    delivered = await hub.broadcast(session, ServerEventType.QUESTION_DELIVERED, {})

    assert delivered == 1
    assert hub.participant_count(session) == 1  # the dead one was evicted


async def test_targeted_send_is_private() -> None:
    """Attention prompts go to one student and must not leak to the class."""
    hub = SessionHub()
    session = uuid4()
    target_id = uuid4()
    target, bystander = _FakeSocket(), _FakeSocket()
    await hub.join(Connection(target, target_id, session))  # type: ignore[arg-type]
    await hub.join(Connection(bystander, uuid4(), session))  # type: ignore[arg-type]

    sent = await hub.send_to_user(session, target_id, ServerEventType.PROMPT_ATTENTION, {})

    assert sent is True
    assert len(target.sent) == 1
    assert bystander.sent == []


async def test_targeted_send_reaches_every_connection_a_student_holds() -> None:
    """Teams on the desktop and in a tab is two sockets for one student.

    Delivering to only the first means an attention prompt can land on a stale
    connection while the call still reports success.
    """
    hub = SessionHub()
    session = uuid4()
    student = uuid4()
    desktop, browser = _FakeSocket(), _FakeSocket()
    await hub.join(Connection(desktop, student, session))  # type: ignore[arg-type]
    await hub.join(Connection(browser, student, session))  # type: ignore[arg-type]

    sent = await hub.send_to_user(session, student, ServerEventType.PROMPT_ATTENTION, {})

    assert sent is True
    assert len(desktop.sent) == 1
    assert len(browser.sent) == 1


async def test_targeted_send_reports_failure_when_the_only_socket_is_dead() -> None:
    hub = SessionHub()
    session = uuid4()
    student = uuid4()
    await hub.join(Connection(_FakeSocket(fail=True), student, session))  # type: ignore[arg-type]

    sent = await hub.send_to_user(session, student, ServerEventType.PROMPT_ATTENTION, {})

    assert sent is False
    assert hub.participant_count(session) == 0  # the dead one was evicted


async def test_an_emptied_room_keeps_its_sequence_counter() -> None:
    """Everyone dropping out briefly must not restart seq at 1.

    Clients track the highest seq they have seen, so a reset reads as a gap.
    """
    hub = SessionHub()
    session = uuid4()
    connection = Connection(_FakeSocket(), uuid4(), session)  # type: ignore[arg-type]

    await hub.join(connection)
    hub.build(session, ServerEventType.PONG, {})
    hub.build(session, ServerEventType.PONG, {})
    await hub.leave(connection)

    assert hub.participant_count(session) == 0
    assert hub.build(session, ServerEventType.PONG, {}).seq == 3


async def test_forget_session_clears_the_counter() -> None:
    """The Phase 3 session-end hook. Only safe once a session has ended."""
    hub = SessionHub()
    session = uuid4()
    hub.build(session, ServerEventType.PONG, {})

    hub.forget_session(session)

    assert hub.build(session, ServerEventType.PONG, {}).seq == 1


async def test_leaving_empties_the_room() -> None:
    hub = SessionHub()
    session = uuid4()
    connection = Connection(_FakeSocket(), uuid4(), session)  # type: ignore[arg-type]

    await hub.join(connection)
    assert hub.participant_count(session) == 1

    await hub.leave(connection)
    assert hub.participant_count(session) == 0
