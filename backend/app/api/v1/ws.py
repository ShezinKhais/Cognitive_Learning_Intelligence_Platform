"""Live session WebSocket endpoint.

Protocol
--------
The client opens the socket and must send an `auth` event first. Anything else
before authentication closes the connection. On success the server replies
`ready`, after which the connection is joined to its session room.

Every ordered server message carries a `seq` that increases monotonically
within its session or authenticated user channel. Clients track the highest
seq they have seen and send it as `last_seq` when reconnecting.

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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AppSettings, DbSession
from app.auth.service import user_from_token
from app.core.security import TokenValidationError
from app.realtime.hub import Connection, hub
from app.schemas.events import (
    AuthPayload,
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


async def _send(
    websocket: WebSocket,
    event_type: ServerEventType,
    data: dict,
) -> None:
    """Send a connection-scoped message.

    seq is 0 because these are not part of a session's ordered stream; clients
    only track gaps in events that carry a non-zero seq.
    """

    event = ServerEvent(
        type=event_type,
        seq=0,
        ts=datetime.now(UTC),
        data=data,
    )

    await websocket.send_json(event.model_dump(mode="json"))


async def _receive_event(
    websocket: WebSocket,
) -> dict[str, Any] | None:
    """Receive one frame and return it as a JSON object.

    Binary frames, invalid JSON and JSON values that are not objects are
    treated as protocol errors rather than server faults.

    Raises WebSocketDisconnect when the peer has disconnected.
    """

    message = await websocket.receive()

    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(
            message.get("code", 1005),
            message.get("reason"),
        )

    text = message.get("text")

    if text is None:
        return None

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None

    return raw if isinstance(raw, dict) else None


async def _authenticate(
    websocket: WebSocket,
    settings: AppSettings,
    db: AsyncSession,
) -> tuple[UUID, UUID | None, int | None] | None:
    """Read and validate the opening auth event.

    Development resolves JWT users from the local Cyber 1 identities.
    Production resolves JWT users through Nour's persisted User table.
    """

    try:
        raw = await asyncio.wait_for(
            _receive_event(websocket),
            AUTH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        await websocket.close(
            code=CLOSE_AUTH_TIMEOUT,
            reason="no auth event received",
        )
        return None
    except WebSocketDisconnect:
        return None

    if raw is None:
        await websocket.close(
            code=CLOSE_BAD_EVENT,
            reason="malformed event",
        )
        return None

    # The first valid protocol event must be authentication.
    if raw.get("type") != ClientEventType.AUTH.value:
        try:
            parse_client_event(raw)
        except PydanticValidationError:
            await websocket.close(
                code=CLOSE_BAD_EVENT,
                reason="malformed event",
            )
            return None

        await websocket.close(
            code=CLOSE_UNAUTHENTICATED,
            reason="auth required first",
        )
        return None

    try:
        _event_type, payload = parse_client_event(raw)
    except PydanticValidationError:
        await websocket.close(
            code=CLOSE_BAD_EVENT,
            reason="malformed auth payload",
        )
        return None

    if not isinstance(payload, AuthPayload):
        await websocket.close(
            code=CLOSE_BAD_EVENT,
            reason="malformed auth payload",
        )
        return None

    try:
        user = await user_from_token(
            payload.token,
            settings,
            db,
        )
    except TokenValidationError as exc:
        log.warning(
            ("security_event=TOKEN_REJECTED transport=websocket reason=%s"),
            str(exc),
        )

        await websocket.close(
            code=CLOSE_UNAUTHENTICATED,
            reason="authentication failed",
        )

        return None

    return user.id, payload.session_id, payload.last_seq


def _session_access_allowed(
    user_id: UUID,
    session_id: UUID | None,
) -> bool:
    """Authorize access to a requested live session.

    Phase 1 fails closed when a specific session is requested because
    authentication proves identity but does not yet prove session membership.
    """

    if session_id is None:
        return True

    log.warning(
        (
            "security_event=ACCESS_DENIED "
            "transport=websocket "
            "user_id=%s "
            "session_id=%s "
            "reason=session_membership_unverified"
        ),
        user_id,
        session_id,
    )

    return False


@router.websocket("/ws/session")
async def session_socket(
    websocket: WebSocket,
    settings: AppSettings,
    db: DbSession,
) -> None:
    await websocket.accept()

    identity = await _authenticate(
        websocket,
        settings,
        db,
    )

    if identity is None:
        return

    user_id, session_id, last_seq = identity

    # A valid JWT alone does not authorize an arbitrary session.
    if not _session_access_allowed(
        user_id,
        session_id,
    ):
        await websocket.close(
            code=CLOSE_FORBIDDEN,
            reason="not permitted to join this session",
        )
        return

    connection = Connection(
        websocket,
        user_id=user_id,
        session_id=session_id,
    )

    try:
        _replayed, resumed_from_seq = await hub.join_and_replay(
            connection,
            last_seq,
        )

        await _send(
            websocket,
            ServerEventType.READY,
            {
                "user_id": str(user_id),
                "session_id": (str(session_id) if session_id else None),
                "resumed_from_seq": resumed_from_seq,
            },
        )

        while True:
            raw = await _receive_event(websocket)

            if raw is None:
                await _send(
                    websocket,
                    ServerEventType.ERROR,
                    {
                        "code": "MALFORMED_EVENT",
                        "detail": "expected a JSON object",
                    },
                )
                continue

            try:
                event_type, _payload = parse_client_event(raw)
            except PydanticValidationError as exc:
                await _send(
                    websocket,
                    ServerEventType.ERROR,
                    {
                        "code": "MALFORMED_EVENT",
                        "detail": (f"{exc.error_count()} invalid field(s)"),
                    },
                )
                continue

            if event_type is ClientEventType.PING:
                await _send(
                    websocket,
                    ServerEventType.PONG,
                    {},
                )
                continue

            # These handlers are connected in Phase 3.
            await _send(
                websocket,
                ServerEventType.ERROR,
                {
                    "code": "NOT_IMPLEMENTED",
                    "detail": (f"{event_type.value} lands in Phase 3"),
                },
            )

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception(
            "websocket failed for user %s",
            user_id,
        )
    finally:
        await hub.leave(connection)
