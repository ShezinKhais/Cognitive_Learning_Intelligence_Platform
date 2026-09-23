"""Registers AI 1's ResponseRecorder and CloseRecorder on the classroom
singleton.

main.py imports this module before calling classroom.check_wiring(), so the
side effects below run at startup.
"""

from __future__ import annotations

from uuid import UUID

from app.core.database import get_session_factory
from app.realtime.classroom import ClosedQuestion, classroom
from app.realtime.hub import hub
from app.repositories.live_event_repository import LiveEventRepository
from app.repositories.question_repository import QuestionRepository
from app.schemas.events import FeedbackResultPayload, ServerEventType
from app.services.live_recorder import LiveCloseRecorder, LivePromptRecorder, LiveResponseRecorder


async def _get_question(question_id: UUID):
    async with get_session_factory()() as db:
        return await QuestionRepository(db).get_by_id(question_id)


async def _store_response(
    *,
    session_id: UUID,
    question_id: UUID,
    user_id: UUID,
    selected_option: int | None,
    free_text: str | None,
    is_correct: bool | None,
    elapsed_ms: int | None,
    submitted_at=None,
):
    async with get_session_factory()() as db:
        try:
            stored = await LiveEventRepository(db).record_response(
                session_id=session_id,
                question_id=question_id,
                user_id=user_id,
                selected_option=selected_option,
                free_text=free_text,
                is_correct=is_correct,
                elapsed_ms=elapsed_ms,
                submitted_at=submitted_at,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return stored


async def _store_close(closed: ClosedQuestion) -> None:
    async with get_session_factory()() as db:
        try:
            await LiveEventRepository(db).close_question_delivery(
                session_id=closed.session_id,
                question_id=closed.question_id,
                eligible_user_ids=set(closed.eligible),
                answered_user_ids=set(closed.answered),
                reason=closed.reason,
                closed_at=closed.closed_at,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _store_prompt_outcome(
    *,
    prompt_id: UUID,
    session_id: UUID,
    user_id: UUID,
    escalation: int,
    sent_at,
    expires_at,
    result: str,
    responded_at,
):
    async with get_session_factory()() as db:
        try:
            await LiveEventRepository(db).record_prompt_outcome(
                prompt_id=prompt_id,
                session_id=session_id,
                user_id=user_id,
                escalation=escalation,
                sent_at=sent_at,
                expires_at=expires_at,
                result=result,
                responded_at=responded_at,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _get_answers(session_id: UUID, question_id: UUID):
    async with get_session_factory()() as db:
        return await LiveEventRepository(db).answers_to_question(session_id, question_id)


async def _send_feedback(session_id: UUID, user_id: UUID, payload: FeedbackResultPayload) -> None:
    await hub.send_to_user(
        session_id, user_id, ServerEventType.FEEDBACK_RESULT, payload.model_dump(mode="json")
    )


classroom.recorder = LiveResponseRecorder(
    get_question=_get_question, store_response=_store_response
)

classroom.close_recorder = LiveCloseRecorder(
    get_question=_get_question,
    store_close=_store_close,
    get_answers=_get_answers,
    send_feedback=_send_feedback,
)
classroom.prompt_recorder = LivePromptRecorder(store_prompt_outcome=_store_prompt_outcome)
