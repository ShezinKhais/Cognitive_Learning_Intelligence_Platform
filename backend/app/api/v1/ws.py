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
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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

AUTH_TIMEOUT_SECONDS = 10


async def _send(websocket: WebSocket, event_type: ServerEventType, data: dict) -> None:
    """Send outside a session context, before a room has been joined."""
    event = ServerEvent(type=event_type, seq=0, ts=datetime.now(UTC), data=data)
    await websocket.send_json(event.model_dump(mode="json"))


async def _authenticate(websocket: WebSocket) -> tuple[UUID, UUID | None] | None:
    """Read and validate the opening `auth` event.

    Token verification is owned by Cyber 1 and shares the logic behind
    `app.api.deps.get_principal`. Until that lands this rejects every
    connection, so no socket can appear authenticated when it is not.
    """
    raw = await websocket.receive_json()

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
            raw = await websocket.receive_json()
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
