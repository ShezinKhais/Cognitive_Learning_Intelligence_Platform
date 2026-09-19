"""Live session WebSocket endpoint.

Protocol
--------
The client opens the socket and must send an `auth` event first. Anything else
before authentication closes the connection. On success the server replies
`ready`, after which the connection is joined to its session room.

Every ordered server message carries a `seq` that increases monotonically
within its session or authenticated user channel. Clients track the highest
seq and stream generation they have seen and send both when reconnecting.

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
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.api.deps import AppSettings, DbSession
from app.auth.service import user_from_token
from app.core.security import TokenValidationError
from app.realtime.hub import CLOSE_TRY_AGAIN_LATER, Connection, hub
from app.repositories.engagement_repository import EngagementRepository
from app.repositories.question_repository import QuestionRepository
from app.repositories.response_repository import ResponseRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.events import (
    AnswerSubmitPayload,
    AttentionSignalPayload,
    AuthPayload,
    ClientEventType,
    PromptAckPayload,
    ServerEvent,
    ServerEventType,
    parse_client_event,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus
from app.services.engagement import compute_engagement, should_send_dynamic_prompt
from app.services.scoring import classify_free_text, score_mcq
from app.services.session_access import session_membership_allowed

log = logging.getLogger("clip.ws")

router = APIRouter()

CLOSE_UNAUTHENTICATED = 4001
CLOSE_FORBIDDEN = 4003
CLOSE_BAD_EVENT = 4400

# Sessions a socket may join. session_membership_allowed only checks
# enrolment/ownership, not lifecycle -- an ended or cancelled session's
# course/instructor rules are still satisfied, so the status gate has to
# live here, at the one call site that means "join the live stream" rather
# than "may this caller see this session at all" (app.api.v1.sessions'
# REST reads reuse session_membership_allowed for the latter and must keep
# working after a session ends).
JOINABLE_SESSION_STATUSES = {SessionStatus.PREPARED.value, SessionStatus.ACTIVE.value}
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


async def _session_access_allowed(
    db: AsyncSession,
    user_id: UUID,
    role: Role,
    session_id: UUID | None,
) -> bool:
    """Authorize access to a requested live session.

    A JWT alone proves identity, not that its holder belongs to this
    particular session -- see app.services.session_access, which this
    delegates to so the WebSocket and REST routes (app.api.v1.sessions) apply
    exactly the same rule.
    """

    if session_id is None:
        return True

    session_repo = SessionRepository(db)
    session_row = await session_repo.get_by_id(session_id)
    if session_row is None:
        log.warning(
            "security_event=ACCESS_DENIED transport=websocket user_id=%s session_id=%s "
            "reason=session_not_found",
            user_id,
            session_id,
        )
        return False

    if session_row.status not in JOINABLE_SESSION_STATUSES:
        log.warning(
            "security_event=ACCESS_DENIED transport=websocket user_id=%s session_id=%s "
            "reason=session_not_joinable status=%s",
            user_id,
            session_id,
            session_row.status,
        )
        return False

    allowed = await session_membership_allowed(db, session_row, user_id=user_id, role=role)
    if not allowed:
        log.warning(
            "security_event=ACCESS_DENIED transport=websocket user_id=%s session_id=%s "
            "reason=not_a_member",
            user_id,
            session_id,
        )
    return allowed


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

    # A valid JWT alone does not authorize an arbitrary session.
    if not await _session_access_allowed(
        db,
        user_id,
        role,
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
        if not await hub.connect(connection, last_seq, stream_id):
            return

        if session_id is not None:
            session_repo = SessionRepository(db)
            await session_repo.record_join(session_id, user_id)
            await db.commit()
            await _send_session_state(websocket, session_repo, session_id)

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

            if session_id is None:
                await _send(
                    websocket,
                    ServerEventType.ERROR,
                    {
                        "code": "NOT_IN_SESSION",
                        "detail": f"{event_type.value} requires an active session",
                    },
                )
                continue

            if event_type is ClientEventType.ANSWER_SUBMIT:
                assert isinstance(payload, AnswerSubmitPayload)
                await _handle_answer_submit(
                    websocket, db, settings, session_id, user_id, role, payload
                )
            elif event_type is ClientEventType.PROMPT_ACK:
                assert isinstance(payload, PromptAckPayload)
                await _handle_prompt_ack(db, payload)
            elif event_type is ClientEventType.SIGNAL_ATTENTION:
                assert isinstance(payload, AttentionSignalPayload)
                await _handle_signal_attention(
                    websocket, db, settings, session_id, user_id, role, payload
                )
            else:
                # ROOM_CONFIRM lands in Phase 6.
                await _send(
                    websocket,
                    ServerEventType.ERROR,
                    {
                        "code": "NOT_IMPLEMENTED",
                        "detail": (f"{event_type.value} lands in a later phase"),
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
        if session_id is not None:
            try:
                await SessionRepository(db).record_leave(session_id, user_id)
                await db.commit()
            except Exception:
                log.exception("could not record session leave for user %s", user_id)
        await hub.leave(connection)


async def _send_session_state(
    websocket: WebSocket,
    session_repo: SessionRepository,
    session_id: UUID,
) -> None:
    row = await session_repo.get_by_id(session_id)
    if row is None:
        return
    open_delivery = await session_repo.get_open_delivery(session_id)
    await _send(
        websocket,
        ServerEventType.SESSION_STATE,
        {
            "session_id": str(session_id),
            "status": row.status,
            "participant_count": await session_repo.participant_count(session_id),
            "active_question_id": (str(open_delivery.question_id) if open_delivery else None),
            "questions_delivered": await session_repo.count_delivered(session_id),
        },
    )


async def _handle_answer_submit(
    websocket: WebSocket,
    db: AsyncSession,
    settings: AppSettings,
    session_id: UUID,
    user_id: UUID,
    role: Role,
    payload: AnswerSubmitPayload,
) -> None:
    if role != Role.STUDENT:
        await _send(
            websocket,
            ServerEventType.ANSWER_RECEIPT,
            {
                "question_id": str(payload.question_id),
                "accepted": False,
                "received_at": datetime.now(UTC).isoformat(),
                "reason": "only students submit answers",
            },
        )
        return

    student = await StudentRepository(db).get_by_user_id(user_id)
    session_repo = SessionRepository(db)
    delivery = await session_repo.get_open_delivery(session_id)

    if student is None or delivery is None or delivery.question_id != payload.question_id:
        await _send(
            websocket,
            ServerEventType.ANSWER_RECEIPT,
            {
                "question_id": str(payload.question_id),
                "accepted": False,
                "received_at": datetime.now(UTC).isoformat(),
                "reason": "this question is not currently open",
            },
        )
        return

    response_repo = ResponseRepository(db)
    if await response_repo.get_for_question(session_id, payload.question_id, student.student_id):
        await _send(
            websocket,
            ServerEventType.ANSWER_RECEIPT,
            {
                "question_id": str(payload.question_id),
                "accepted": False,
                "received_at": datetime.now(UTC).isoformat(),
                "reason": "already answered",
            },
        )
        return

    question = await QuestionRepository(db).get_by_id(payload.question_id)
    if question is None:
        return

    answer_shape_matches = (payload.selected_option is not None) == (
        question.question_type == "mcq"
    )
    if not answer_shape_matches:
        await _send(
            websocket,
            ServerEventType.ANSWER_RECEIPT,
            {
                "question_id": str(payload.question_id),
                "accepted": False,
                "received_at": datetime.now(UTC).isoformat(),
                "reason": "answer shape does not match the question type",
            },
        )
        return

    if payload.selected_option is not None:
        scored = score_mcq(question, payload.selected_option)
    else:
        scored = classify_free_text(question, payload.free_text or "")

    await response_repo.record(
        session_id=session_id,
        question_id=payload.question_id,
        student_id=student.student_id,
        selected_option=payload.selected_option,
        free_text=payload.free_text,
        elapsed_ms=payload.client_elapsed_ms,
        is_correct=scored.correct,
    )
    await db.commit()

    await _send(
        websocket,
        ServerEventType.ANSWER_RECEIPT,
        {
            "question_id": str(payload.question_id),
            "accepted": True,
            "received_at": datetime.now(UTC).isoformat(),
            "reason": None,
        },
    )

    await hub.send_to_user(
        session_id,
        user_id,
        ServerEventType.FEEDBACK_RESULT,
        {
            "question_id": str(payload.question_id),
            "correct": scored.correct,
            "explanation": scored.explanation,
            "source_slide": scored.source_slide,
        },
    )

    await _update_engagement(db, settings, session_id, user_id, student.student_id, attention=None)


async def _handle_prompt_ack(db: AsyncSession, payload: PromptAckPayload) -> None:
    await EngagementRepository(db).acknowledge_prompt(
        payload.prompt_id, dismissed=payload.dismissed
    )
    await db.commit()


async def _handle_signal_attention(
    websocket: WebSocket,  # noqa: ARG001 - kept for a consistent handler signature
    db: AsyncSession,
    settings: AppSettings,
    session_id: UUID,
    user_id: UUID,
    role: Role,
    payload: AttentionSignalPayload,
) -> None:
    if role != Role.STUDENT:
        return  # engagement is only meaningful for students

    student = await StudentRepository(db).get_by_user_id(user_id)
    if student is None:
        return

    await _update_engagement(
        db, settings, session_id, user_id, student.student_id, attention=payload
    )


async def _update_engagement(
    db: AsyncSession,
    settings: AppSettings,
    session_id: UUID,
    user_id: UUID,
    student_id: UUID,
    attention: AttentionSignalPayload | None,
) -> None:
    session_repo = SessionRepository(db)
    response_repo = ResponseRepository(db)
    engagement_repo = EngagementRepository(db)

    delivered = await session_repo.count_delivered(session_id)
    attempt_rate = (
        (await response_repo.count_attempted(session_id, student_id)) / delivered
        if delivered > 0
        else None
    )

    computation = compute_engagement(attempt_rate, attention)

    await engagement_repo.record(
        session_id=session_id,
        student_id=student_id,
        attempt_rate=attempt_rate or 0.0,
        attention_signal=computation.attention_signal_label,
        engagement_score=computation.score,
        status=computation.status.value,
        confidence=computation.confidence,
        signals_available=",".join(computation.signals_available),
    )
    await db.commit()

    await hub.send_to_user(
        session_id,
        user_id,
        ServerEventType.ENGAGEMENT_UPDATE,
        {
            "score": computation.score,
            "status": computation.status.value,
            "confidence": computation.confidence,
        },
    )

    prompts_sent = await engagement_repo.count_prompts(session_id, student_id)
    if should_send_dynamic_prompt(
        computation,
        prompts_already_sent=prompts_sent,
        max_per_student=settings.dynamic_prompt_max_per_student,
    ):
        prompt = await engagement_repo.record_prompt(
            session_id=session_id,
            student_id=student_id,
            prompt_text="Still with us? Tap to let your lecturer know you're following along.",
            trigger_reason=computation.status.value,
        )
        await db.commit()
        await hub.send_to_user(
            session_id,
            user_id,
            ServerEventType.PROMPT_ATTENTION,
            {
                "prompt_id": str(prompt.prompt_id),
                "message": prompt.prompt_text,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
                "escalation": prompts_sent + 1,
            },
        )
