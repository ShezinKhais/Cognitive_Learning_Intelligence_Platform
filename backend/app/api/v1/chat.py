"""The tutor's chat route.

Owner: General CS, Phase 5.

A student in a session asks the tutor a question and reads the reply as it is
written. The reply is NDJSON, one event to a line, which is what the student
panel's chatProtocol.ts parses. Closing the connection is how a student
stops a reply: the server notices, and the model is stopped with it.

Everything that can refuse the request does so before the reply starts, with
an ordinary error response: who is asking, whether they belong to the
session, whether they have consented, and whether they are asking too often.
Once the stream is open, a problem is an event on it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, require_consents, require_roles
from app.core.errors import NotFoundError
from app.realtime.classroom import classroom
from app.schemas.chat import ChatRequest
from app.schemas.identity import ConsentType, Role
from app.schemas.session import SessionStatus
from app.services import session_lifecycle, tutor_chat

router = APIRouter(
    prefix="/sessions",
    tags=["chat"],
    dependencies=[
        Depends(require_consents(ConsentType.TERMS)),
        # The tutor is the students'. Staff reach a session through its
        # controls, and have the material itself.
        Depends(require_roles(Role.STUDENT)),
    ],
)

_EVENTS = (
    "One JSON object per line, each with `type` and `request_id`. `accepted` comes "
    "first. Then either `delta` events carrying `text`, `citation` events carrying a "
    "`citation` (`id`, `material_title`, `source_page`, `source_slide`, `excerpt`), "
    "`follow_up` events carrying a `prompt`, and `completed`; or one of `unsupported` "
    "(with a `reason`), `empty_retrieval` and `error` (with a `detail`)."
)


@router.post(
    "/{session_id}/chat",
    response_class=StreamingResponse,
    responses={
        200: {"description": _EVENTS, "content": {tutor_chat.NDJSON: {}}},
        404: {"description": "No such session, or the student does not belong to it."},
        409: {"description": "The tutor is still answering this student's last question."},
        429: {"description": "The student is asking too often."},
    },
)
async def session_chat(
    session_id: UUID,
    payload: ChatRequest,
    principal: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    """Ask the tutor a question about the session's material.

    The reply streams as it is written. To stop it, close the connection.
    """
    live = await session_lifecycle.joinable_session(
        db, principal.user_id, principal.role, session_id
    )
    if live is None:
        # A session that does not exist and one the student is not enrolled
        # for are refused alike, so a session id cannot be probed.
        raise NotFoundError("Session was not found.", {"session_id": str(session_id)})

    open_question_id = classroom.state(session_id, SessionStatus(live.status)).active_question_id
    context = await tutor_chat.prepare(db, live, principal.user_id, open_question_id)
    # Last, so a request refused for any other reason costs the student
    # nothing against their limit.
    tutor_chat.get_chat_limiter().admit(principal.user_id)

    return StreamingResponse(
        tutor_chat.TutorExchange(context).lines(payload.request_id, payload.question),
        media_type=tutor_chat.NDJSON,
        headers={
            "Cache-Control": "no-store",
            # Tells a proxy not to hold the reply back until it is complete.
            "X-Accel-Buffering": "no",
        },
    )
