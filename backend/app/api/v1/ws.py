"""Live session WebSocket endpoint.

Protocol
--------
The client opens the socket and must send an `auth` event first. Anything else
before authentication closes the connection. On success the server replies
`ready`, after which the connection is joined to its session room, or with no
session_id to the user's own channel.

Joining a session needs a seat in it: the lecturer who runs it, an admin, or
a student enrolled on its course, while it is prepared or active. After
`ready` and any replay, a session connection is sent `session.state`, the
question that is open (unless this student has answered it) and any
attention prompt still waiting on this student.

Every ordered server message carries a `seq` that increases monotonically
within its session or authenticated user channel. Clients track the highest
seq and stream generation they have seen and send both when reconnecting.
Events for one user alone, such as an answer receipt, carry seq 0.

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
from starlette.websockets import WebSocketState

from app.api.deps import AppSettings, DbSession
from app.auth.service import user_from_token
from app.core.security import TokenValidationError
from app.realtime.classroom import classroom
from app.realtime.hub import CLOSE_TRY_AGAIN_LATER, Connection, hub
from app.schemas.events import (
    AnswerSubmitPayload,
    AuthPayload,
    ClientEventType,
    PromptAckPayload,
    ServerEvent,
    ServerEventType,
    parse_client_event,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus
from app.services.session_lifecycle import joinable_session

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

    The hub closes a socket from another task when a delivery to it fails. A
    ping already on its way was then answered on a closed socket, Starlette
    raised RuntimeError, and the endpoint logged a traceback for what is an
    ordinary disconnect. It is reported as the disconnect it is instead. No
    await separates the check from the send, so the state cannot change between.
    """
    if websocket.application_state is not WebSocketState.CONNECTED:
        raise WebSocketDisconnect(code=CLOSE_TRY_AGAIN_LATER)

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
) -> tuple[UUID, Role, UUID | None, int | None, UUID | None] | None:
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

    return user.id, user.role, payload.session_id, payload.last_seq, payload.stream_id


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

    user_id, role, session_id, last_seq, stream_id = identity

    welcome = None
    if session_id is not None:
        # A valid JWT alone does not authorize an arbitrary session.
        try:
            row = await joinable_session(db, user_id, role, session_id)
            if row is not None:
                await classroom.restore(db, row)
        except Exception:
            log.exception("could not check membership of session %s", session_id)
            await websocket.close(
                code=CLOSE_TRY_AGAIN_LATER,
                reason="session unavailable, try again",
            )
            return
        if row is None:
            log.warning(
                (
                    "security_event=ACCESS_DENIED "
                    "transport=websocket "
                    "user_id=%s "
                    "session_id=%s "
                    "reason=not_a_session_member"
                ),
                user_id,
                session_id,
            )
            await websocket.close(
                code=CLOSE_FORBIDDEN,
                reason="not permitted to join this session",
            )
            return
        recorded = SessionStatus(row.status)

        async def welcome() -> list[tuple[ServerEventType, dict]]:
            return classroom.welcome(session_id, recorded, user_id, role)

    # The socket lives for the whole class. Its database session must not
    # hold a pooled connection that long, or forty students exhaust the pool.
    await db.close()

    connection = Connection(
        websocket,
        user_id=user_id,
        session_id=session_id,
        role=role,
    )

    try:
        if not await hub.connect(connection, last_seq, stream_id, welcome):
            return

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
                event_type, payload = parse_client_event(raw)
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

            if isinstance(payload, AnswerSubmitPayload | PromptAckPayload):
                if session_id is None:
                    await _send(
                        websocket,
                        ServerEventType.ERROR,
                        {
                            "code": "NOT_IN_SESSION",
                            "detail": f"join a session to send {event_type}",
                        },
                    )
                elif isinstance(payload, PromptAckPayload):
                    if not await classroom.acknowledge_prompt(session_id, user_id, payload):
                        # Usually an acknowledgement that crossed the prompt's
                        # expiry in flight. The client can drop the prompt.
                        await _send(
                            websocket,
                            ServerEventType.ERROR,
                            {"code": "PROMPT_NOT_OPEN", "detail": "that prompt is no longer open"},
                        )
                else:
                    receipt = await classroom.submit(session_id, user_id, role, payload)
                    # To every tab the student has open, so none of them offers
                    # the question again.
                    await hub.send_to_user(
                        session_id,
                        user_id,
                        ServerEventType.ANSWER_RECEIPT,
                        receipt.model_dump(mode="json"),
                    )
                continue

            # Attention signals and breakout rooms belong to later workstreams.
            await _send(
                websocket,
                ServerEventType.ERROR,
                {
                    "code": "NOT_IMPLEMENTED",
                    "detail": f"{event_type.value} is not handled yet",
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
