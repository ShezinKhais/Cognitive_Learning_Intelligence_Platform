"""WebSocket handshake and protocol.

The hub itself is exercised directly rather than through a socket, so these run
without a server or a database.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.schemas.events import (
    ClientEventType,
    ServerEventType,
)

from .database_support import require_database
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


def _session_join_close_code(client: TestClient, session_id: UUID) -> int:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "student@clip.example.com", "password": STUDENT_PASSWORD},
    )
    token = login.json()["access_token"]
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": ClientEventType.AUTH.value,
                    "data": {"token": token, "session_id": str(session_id)},
                }
            )
            ws.receive_json()
    return exc.value.code


def test_a_session_that_cannot_be_checked_is_try_again_not_a_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Membership is read from the database. When that fails the client is
    told to reconnect, rather than the socket dying with a server error."""

    async def unreachable(*args: object) -> None:
        raise ConnectionRefusedError("database down")

    monkeypatch.setattr("app.api.v1.ws.joinable_session", unreachable)

    assert _session_join_close_code(client, uuid4()) == 1013


def test_socket_rejects_unverified_session_membership(
    client: TestClient,
) -> None:
    """A valid token does not authorize an arbitrary session."""
    require_database()
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


def test_ready_is_the_first_frame_even_with_an_upload_in_progress(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Joining before ready made the connection visible to delivery mid
    handshake, so a progress frame could arrive first and be dropped by any
    client that waits for ready as the protocol says it should.

    The race is forced here rather than left to timing: the join itself
    publishes progress, which is exactly the moment an upload already running
    for this lecturer would.
    """
    from app.api.v1 import ws as ws_module
    from app.auth.store import LECTURER_ID

    from .dev_credentials import LECTURER_PASSWORD

    real_join = ws_module.hub.join

    async def join_while_an_upload_reports(connection) -> None:
        # An upload reports mid-handshake, from its own task as a real one would.
        asyncio.get_running_loop().create_task(
            ws_module.hub.send_to_user_channel(
                connection.user_id,
                ServerEventType.MATERIAL_PROGRESS,
                {"material_id": str(uuid4()), "stage": "extracting", "percent": 20},
            )
        )
        await asyncio.sleep(0)
        await real_join(connection)

    monkeypatch.setattr(ws_module.hub, "join", join_while_an_upload_reports)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD},
    )
    token = login.json()["access_token"]

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": ClientEventType.AUTH.value, "data": {"token": token}})
        first = ws.receive_json()
        second = ws.receive_json()

    assert first["type"] == ServerEventType.READY
    assert first["data"]["user_id"] == str(LECTURER_ID)
    assert second["type"] == ServerEventType.MATERIAL_PROGRESS


async def test_a_reply_on_a_socket_the_hub_closed_is_a_disconnect_not_an_error() -> None:
    """A ping in flight when the hub closed the socket was answered anyway,
    and Starlette's RuntimeError was logged as a websocket failure."""
    from starlette.websockets import WebSocketState

    from app.api.v1 import ws as ws_module

    class Closed:
        application_state = WebSocketState.DISCONNECTED
        sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            raise RuntimeError('Cannot call "send" once a close message has been sent.')

    with pytest.raises(WebSocketDisconnect):
        await ws_module._send(Closed(), ServerEventType.PONG, {})


def _is_connected(hub, user_id) -> bool:
    stream = hub._streams.get(user_id)
    return stream is not None and any(c.user_id == user_id for c in stream.members)


def test_a_closed_socket_is_removed_from_the_hub(client: TestClient) -> None:
    """Without the leave in finally, every dead connection stays registered."""
    from app.api.v1 import ws as ws_module
    from app.auth.store import STUDENT_ID

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "student@clip.example.com", "password": STUDENT_PASSWORD},
    ).json()["access_token"]

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": ClientEventType.AUTH.value, "data": {"token": token}})
        ws.receive_json()
        # The pong comes from the receive loop, which starts after the join.
        ws.send_json({"type": ClientEventType.PING.value, "data": {}})
        ws.receive_json()
        assert _is_connected(ws_module.hub, STUDENT_ID)

    assert not _is_connected(ws_module.hub, STUDENT_ID)
