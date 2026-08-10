"""Live session WebSocket endpoint.

Protocol
--------
The client opens the socket and must send an `auth` event first. Anything else
before authentication closes the connection. On success the server replies
`ready`, after which the connection is joined to its session room.

Every server message carries a `seq` that increases monotonically within a
session. Clients track the highest seq they have seen and send it as `last_seq`
when reconnecting.

Closing codes
-------------
4001  authentication required or failed
4003  not permitted to join this session
4400  malformed event
4408  no auth event arrived within the timeout
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError as PydanticValidationError

from app.realtime.hub import Connection, hub
from app.schemas.events import (
    ClientEventType,
    ServerEvent,
    ServerEventType,
    parse_client_event,
)

log = logging.getLogger("clip.ws")

router = APIRouter()

CLOSE_UNAUTHENTICATED = 4001
CLOSE_FORBIDDEN = 4003
CLOSE_BAD_EVENT = 4400
CLOSE_AUTH_TIMEOUT = 4408

# A socket that connects and then says nothing would otherwise hold a slot open
# for the lifetime of the process.
AUTH_TIMEOUT_SECONDS = 10


async def _send(websocket: WebSocket, event_type: ServerEventType, data: dict) -> None:
    """Send a connection-scoped message.

    seq is 0 because these are not part of a session's ordered stream; clients
    only track gaps in events that carry a non-zero seq.
    """
    event = ServerEvent(type=event_type, seq=0, ts=datetime.now(UTC), data=data)
    await websocket.send_json(event.model_dump(mode="json"))


async def _receive_event(websocket: WebSocket) -> dict[str, Any] | None:
    """Receive one frame and return it as a JSON object, or None if it is not one.

    Everything past this point may assume it holds a dict. `receive_json` cannot
    give that guarantee: a binary frame raises KeyError, a text frame that is not
    JSON raises JSONDecodeError, and a valid JSON scalar or array returns
    something that has no `.get`. All three are protocol errors from an
    unauthenticated caller, so they are decoded here into a single None the
    caller turns into a close code, rather than escaping as a server fault.

    Raises WebSocketDisconnect when the peer has gone, which callers must let
    through: there is no socket left to send a close frame on.
    """
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1005), message.get("reason"))

    text = message.get("text")
    if text is None:  # binary frame; the protocol is JSON text only
        return None

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None

    return raw if isinstance(raw, dict) else None


async def _authenticate(websocket: WebSocket) -> tuple[UUID, UUID | None] | None:
    """Read and validate the opening `auth` event.

    Token verification is owned by Cyber 1 and shares the logic behind
    `app.api.deps.get_principal`. Until that lands this rejects every
    connection, so no socket can appear authenticated when it is not.
    """
    try:
        raw = await asyncio.wait_for(_receive_event(websocket), AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        await websocket.close(code=CLOSE_AUTH_TIMEOUT, reason="no auth event received")
        return None
    except WebSocketDisconnect:
        return None

    if raw is None:
        await websocket.close(code=CLOSE_BAD_EVENT, reason="malformed event")
        return None

    # Peek at the type before validating the payload so a non-auth first event
    # is reported as an auth failure rather than a malformed one.
    if raw.get("type") != ClientEventType.AUTH.value:
        try:
            parse_client_event(raw)
        except PydanticValidationError:
            await websocket.close(code=CLOSE_BAD_EVENT, reason="malformed event")
            return None
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="auth required first")
        return None

    try:
        parse_client_event(raw)
    except PydanticValidationError:
        await websocket.close(code=CLOSE_BAD_EVENT, reason="malformed auth payload")
        return None

    await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="token verification not implemented")
    return None


@router.websocket("/ws/session")
async def session_socket(websocket: WebSocket) -> None:
    await websocket.accept()

    identity = await _authenticate(websocket)
    if identity is None:
        return

    user_id, session_id = identity
    connection = Connection(websocket, user_id=user_id, session_id=session_id)
    await hub.join(connection)

    try:
        await _send(
            websocket,
            ServerEventType.READY,
            {"user_id": str(user_id), "session_id": str(session_id) if session_id else None},
        )

        while True:
            raw = await _receive_event(websocket)
            if raw is None:
                # Same tolerance as a bad payload below: a student's socket must
                # survive one corrupt frame rather than dropping them from the
                # lecture, so this reports and keeps listening.
                await _send(
                    websocket,
                    ServerEventType.ERROR,
                    {"code": "MALFORMED_EVENT", "detail": "expected a JSON object"},
                )
                continue

            try:
                event_type, _payload = parse_client_event(raw)
            except PydanticValidationError as exc:
                # A bad payload closes nothing: the client can correct and retry.
                await _send(
                    websocket,
                    ServerEventType.ERROR,
                    {"code": "MALFORMED_EVENT", "detail": f"{exc.error_count()} invalid field(s)"},
                )
                continue

            if event_type is ClientEventType.PING:
                await _send(websocket, ServerEventType.PONG, {})
                continue

            # answer.submit, prompt.ack, signal.attention and room.confirm are
            # routed to their handlers in Phase 3, once the scheduler exists.
            await _send(
                websocket,
                ServerEventType.ERROR,
                {"code": "NOT_IMPLEMENTED", "detail": f"{event_type.value} lands in Phase 3"},
            )

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("websocket failed for user %s", user_id)
    finally:
        await hub.leave(connection)
