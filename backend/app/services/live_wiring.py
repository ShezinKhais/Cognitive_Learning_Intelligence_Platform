"""Registers AI 1's ResponseRecorder on the classroom singleton.

main.py imports this module before calling classroom.check_wiring(), so the
side effect below runs at startup. The close recorder is not registered yet:
LiveCloseRecorder needs a way to look up a question's stored answers that
BBIS's LiveEventRepository does not expose yet.
"""

from __future__ import annotations

from uuid import UUID

from app.core.database import get_session_factory
from app.realtime.classroom import classroom
from app.repositories.live_event_repository import LiveEventRepository
from app.repositories.question_repository import QuestionRepository
from app.services.live_recorder import LiveResponseRecorder


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


classroom.recorder = LiveResponseRecorder(
    get_question=_get_question, store_response=_store_response
)
