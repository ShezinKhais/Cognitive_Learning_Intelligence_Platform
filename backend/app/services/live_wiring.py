"""Installs the stores behind the live classroom's seams.

AI 1 scores answers and works out reveals (live_recorder.py), BBIS stores
answers, closes, prompt outcomes and attendance (LiveEventRepository), and
Cyber 1 reads comprehension (DatabaseComprehensionSource) and keeps the
lecturer's alerts (alert_store.py), and each student's attention signals are
summarised per minute into BBIS's attention_signal_summary. main.py calls
install_live_store() in its lifespan, before classroom.check_wiring() reports
anything still missing.

The classroom calls these concurrently, so every call opens its own session.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.database import get_session_factory
from app.models.question import Question
from app.models.student_response import StudentResponse
from app.realtime.classroom import Classroom
from app.realtime.recorders import Attendance, AttentionWindow, ClosedQuestion, PromptOutcome
from app.repositories import attention_signal_repository
from app.repositories.comprehension_repository import DatabaseComprehensionSource
from app.repositories.live_event_repository import LiveEventRepository
from app.repositories.question_repository import QuestionRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.session import ClassComprehensionAlert
from app.services import free_text_marking
from app.services.alert_store import store_comprehension_alert
from app.services.comprehension_writer import label_response
from app.services.live_recorder import LiveCloseRecorder, LiveResponseRecorder

log = logging.getLogger("clip.classroom")


@asynccontextmanager
async def _recording() -> AsyncIterator[LiveEventRepository]:
    """One committed write. A failure is rolled back when the session closes."""
    async with get_session_factory()() as db:
        yield LiveEventRepository(db)
        await db.commit()


async def _get_question(question_id: UUID) -> Question | None:
    async with get_session_factory()() as db:
        return await QuestionRepository(db).get_by_id(question_id)


async def _get_answers(session_id: UUID, question_id: UUID) -> dict[UUID, StudentResponse]:
    async with get_session_factory()() as db:
        return await LiveEventRepository(db).answers_to_question(session_id, question_id)


async def _store_response(**response: Any) -> StudentResponse:
    async with _recording() as events:
        stored = await events.record_response(**response)
        # In the answer's transaction: stored together or not at all.
        await label_response(events.session, stored)
    if stored.free_text is not None and stored.is_correct is None:
        # Marked once stored, without keeping the student waiting.
        free_text_marking.mark_later(stored.response_id, stored.question_id, stored.free_text)
    return stored


async def _store_close(closed: ClosedQuestion) -> None:
    async with _recording() as events:
        await events.close_question_delivery(
            session_id=closed.session_id,
            question_id=closed.question_id,
            eligible_user_ids=set(closed.eligible),
            answered_user_ids=set(closed.answered),
            reason=closed.reason,
            closed_at=closed.closed_at,
        )


class _Engagement:
    """BBIS's record of prompt outcomes and attendance."""

    async def record_prompt(self, outcome: PromptOutcome) -> None:
        async with _recording() as events:
            await events.record_prompt_outcome(
                prompt_id=outcome.prompt_id,
                session_id=outcome.session_id,
                user_id=outcome.user_id,
                escalation=outcome.escalation,
                sent_at=outcome.sent_at,
                expires_at=outcome.expires_at,
                result=outcome.result,
                responded_at=outcome.responded_at,
            )

    async def record_join(self, joined: Attendance) -> None:
        async with _recording() as events:
            await events.record_participant_join(
                session_id=joined.session_id, user_id=joined.user_id, joined_at=joined.at
            )

    async def record_leave(self, left: Attendance) -> None:
        async with _recording() as events:
            await events.record_participant_leave(
                session_id=left.session_id, user_id=left.user_id, left_at=left.at
            )


class _Alerts:
    """The lecturer's alerts, kept so they survive a refresh and the session."""

    async def record_alert(self, alert: ClassComprehensionAlert) -> None:
        await store_comprehension_alert(alert)


class _AttentionSummaries:
    """BBIS's per-minute attention summaries, for the analytics layer."""

    async def record_windows(self, windows: Sequence[AttentionWindow]) -> None:
        async with get_session_factory()() as db:
            # The classroom knows students by user id; the table, like the
            # rest of the contract, by student.student_id.
            student_ids = await StudentRepository(db).student_ids_by_user(
                list({w.user_id for w in windows})
            )
            for window in windows:
                student_id = student_ids.get(window.user_id)
                if student_id is None:
                    continue
                # Each in a savepoint of its own, so a minute already stored
                # (a retry, or a restart mid-minute) costs only that minute.
                try:
                    async with db.begin_nested():
                        await attention_signal_repository.save_summary(
                            db,
                            session_id=window.session_id,
                            student_id=student_id,
                            window_start=window.window_start,
                            summary=attention_signal_repository.summarise(window.signals),
                        )
                except IntegrityError:
                    log.info(
                        "attention minute %s in session %s was already stored",
                        window.window_start,
                        window.session_id,
                    )
            await db.commit()


def install_live_store(room: Classroom) -> None:
    room.recorder = LiveResponseRecorder(get_question=_get_question, store_response=_store_response)
    room.close_recorder = LiveCloseRecorder(
        get_question=_get_question, store_close=_store_close, get_answers=_get_answers
    )
    room.prompt_recorder = room.participant_recorder = _Engagement()
    room.comprehension_source = DatabaseComprehensionSource()
    room.alert_recorder = _Alerts()
    room.attention_recorder = _AttentionSummaries()
