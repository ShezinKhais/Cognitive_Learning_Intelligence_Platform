"""Live session lifecycle: starting, ending, the question cycle and delivery.

Owner: General CS, Phase 3.

A delivered question closes itself: `deliver` schedules a task that waits
`window_seconds` and then closes the question unless it has already been
closed (a lecturer manually triggering the next question closes the current
one early). `start` schedules a second task per session that delivers the
next staged question automatically every `interval_seconds`, so a lecturer
who never touches the manual trigger still gets a live session. Both tasks
open their own database session through `get_session_factory`, the same
pattern app.services.jobs uses for material processing: the request that
called `start` or `deliver` returns long before either timer fires.

Durations are passed in by the caller (which reads them from Settings) rather
than read from Settings in here, so a test can run the whole cycle in
milliseconds without patching global configuration.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.core.database import get_session_factory
from app.models.question import Question
from app.repositories.question_repository import QuestionRepository
from app.repositories.response_repository import ResponseRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.events import AlertKind, QuestionCloseReason, ServerEventType
from app.services.engagement import evaluate_comprehension_alert

log = logging.getLogger("clip.session_lifecycle")


@dataclass(frozen=True)
class DeliveryHandle:
    delivery_id: uuid.UUID
    question: Question
    closes_at_seconds: float


class SessionLifecycle:
    """One instance per process, same lifetime as the realtime hub it drives."""

    def __init__(self) -> None:
        self._close_tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._cycle_tasks: dict[uuid.UUID, asyncio.Task] = {}

    # --- Session-level cycle -------------------------------------------------

    def start_cycle(
        self,
        session_id: uuid.UUID,
        *,
        interval_seconds: float,
        window_seconds: int,
        min_respondents: int,
        alert_threshold: float,
    ) -> None:
        """Begin automatically delivering the next staged question on a timer.

        A no-op if a cycle is already running for this session -- start_session
        is not expected to be called twice, but a stray retry must not spawn a
        second timer racing the first.
        """
        if session_id in self._cycle_tasks:
            return

        task = asyncio.create_task(
            self._run_cycle(
                session_id,
                interval_seconds=interval_seconds,
                window_seconds=window_seconds,
                min_respondents=min_respondents,
                alert_threshold=alert_threshold,
            ),
            name=f"session-cycle-{session_id}",
        )
        self._cycle_tasks[session_id] = task
        task.add_done_callback(lambda _: self._cycle_tasks.pop(session_id, None))

    def stop_cycle(self, session_id: uuid.UUID) -> None:
        task = self._cycle_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()

        close_task = self._close_tasks.pop(session_id, None)
        if close_task is not None:
            close_task.cancel()

    async def end_session(self, db, session_repo: SessionRepository, session_row) -> object:
        """Transition a session to ended and tear down its live state.

        Shared by the lecturer's REST end route and the Teams meeting-ended
        webhook (app.api.v1.teams) so a session ends the same way regardless
        of what triggered it -- see PHASES.md's "automatic session creation
        and archival" for Teams meetings.
        """
        from app.realtime.hub import hub

        row = await session_repo.transition(session_row, status="ended")
        await db.commit()

        self.stop_cycle(session_row.session_id)

        await hub.broadcast(
            session_row.session_id,
            ServerEventType.SESSION_STATE,
            {
                "session_id": str(session_row.session_id),
                "status": row.status,
                "participant_count": await session_repo.participant_count(session_row.session_id),
                "active_question_id": None,
                "questions_delivered": await session_repo.count_delivered(session_row.session_id),
            },
        )
        hub.forget_session(session_row.session_id)
        return row

    async def _run_cycle(
        self,
        session_id: uuid.UUID,
        *,
        interval_seconds: float,
        window_seconds: int,
        min_respondents: int,
        alert_threshold: float,
    ) -> None:
        try:
            while True:
                await asyncio.sleep(interval_seconds)

                async with get_session_factory()() as db:
                    session_repo = SessionRepository(db)
                    row = await session_repo.get_by_id(session_id)
                    if row is None or row.status != "active":
                        return

                    open_delivery = await session_repo.get_open_delivery(session_id)
                    if open_delivery is not None:
                        continue  # a question is already live; wait for it to close

                    question = await session_repo.next_staged_question(session_id)
                    if question is None:
                        continue  # nothing left staged; the lecturer can add more

                    await self._deliver_locked(
                        db,
                        session_repo,
                        session_id=session_id,
                        question=question,
                        window_seconds=window_seconds,
                        min_respondents=min_respondents,
                        alert_threshold=alert_threshold,
                    )
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("session cycle for %s stopped unexpectedly", session_id)

    # --- Delivery -------------------------------------------------------------

    async def deliver(
        self,
        db,  # AsyncSession
        *,
        session_id: uuid.UUID,
        question: Question,
        window_seconds: int,
        min_respondents: int,
        alert_threshold: float,
    ) -> DeliveryHandle:
        """Deliver a question now, closing whatever was already open.

        Used by both the manual trigger route and the automatic cycle, so
        "the scheduler uses the same internal path" (PHASES.md) is literally
        true rather than two implementations that can drift apart.
        """
        session_repo = SessionRepository(db)
        return await self._deliver_locked(
            db,
            session_repo,
            session_id=session_id,
            question=question,
            window_seconds=window_seconds,
            min_respondents=min_respondents,
            alert_threshold=alert_threshold,
        )

    async def _deliver_locked(
        self,
        db,
        session_repo: SessionRepository,
        *,
        session_id: uuid.UUID,
        question: Question,
        window_seconds: int,
        min_respondents: int,
        alert_threshold: float,
    ) -> DeliveryHandle:
        from app.realtime.hub import hub  # local import: hub imports nothing here, avoids a cycle

        open_delivery = await session_repo.get_open_delivery(session_id)
        if open_delivery is not None:
            await self._close_delivery(
                db,
                session_repo,
                delivery=open_delivery,
                reason=QuestionCloseReason.LECTURER_CLOSED,
                min_respondents=min_respondents,
                alert_threshold=alert_threshold,
            )

        question_repo = QuestionRepository(db)
        await question_repo.mark_delivered(question)

        delivery = await session_repo.record_delivery(
            session_id=session_id,
            question_id=question.question_id,
            window_seconds=window_seconds,
        )

        await hub.broadcast(
            session_id,
            ServerEventType.QUESTION_DELIVERED,
            {
                "question_id": str(question.question_id),
                "prompt": question.question_text,
                "options": question.options,
                "closes_at": _closes_at_iso(window_seconds),
                "window_seconds": window_seconds,
                "source_slide": question.source_slide,
            },
        )

        close_task = asyncio.create_task(
            self._close_after_window(
                session_id,
                delivery.delivery_id,
                window_seconds=window_seconds,
                min_respondents=min_respondents,
                alert_threshold=alert_threshold,
            ),
            name=f"question-close-{delivery.delivery_id}",
        )
        self._close_tasks[session_id] = close_task
        close_task.add_done_callback(lambda _: self._close_tasks.pop(session_id, None))

        return DeliveryHandle(
            delivery_id=delivery.delivery_id,
            question=question,
            closes_at_seconds=window_seconds,
        )

    async def _close_after_window(
        self,
        session_id: uuid.UUID,
        delivery_id: uuid.UUID,
        *,
        window_seconds: int,
        min_respondents: int,
        alert_threshold: float,
    ) -> None:
        try:
            await asyncio.sleep(window_seconds)
            async with get_session_factory()() as db:
                session_repo = SessionRepository(db)
                delivery = await session_repo.get_delivery(delivery_id)
                if delivery is None or delivery.closed_at is not None:
                    return  # already closed by a manual trigger
                await self._close_delivery(
                    db,
                    session_repo,
                    delivery=delivery,
                    reason=QuestionCloseReason.WINDOW_ELAPSED,
                    min_respondents=min_respondents,
                    alert_threshold=alert_threshold,
                )
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("closing delivery %s failed", delivery_id)

    async def _close_delivery(
        self,
        db,
        session_repo: SessionRepository,
        *,
        delivery,  # DeliveredQuestion
        reason: QuestionCloseReason,
        min_respondents: int,
        alert_threshold: float,
    ) -> None:
        from app.realtime.hub import hub

        response_repo = ResponseRepository(db)
        # Participants are addressed by user_id (the WebSocket's identity);
        # responses and missed rows are addressed by student_id. A lecturer or
        # admin observer is a participant but never a respondent, so mapping
        # through Student here is what keeps them out of "eligible" instead of
        # inflating it or, worse, letting the id spaces collide by accident.
        participant_user_ids = set(await session_repo.active_participant_ids(delivery.session_id))
        currently_eligible_student_ids = await _only_students(db, participant_user_ids)
        responded_ids = await response_repo.responded_student_ids(
            delivery.session_id, delivery.question_id
        )
        # A student who answered and then disconnected is still counted as
        # eligible for this question -- they were present when it mattered.
        # Only a student still present and silent is "missed".
        eligible_ids = currently_eligible_student_ids | responded_ids
        missed_ids = currently_eligible_student_ids - responded_ids

        question_repo = QuestionRepository(db)
        question = await question_repo.get_by_id(delivery.question_id)
        if missed_ids:
            await response_repo.record_missed(delivery.session_id, delivery.question_id, missed_ids)

        respondent_count = len(responded_ids)
        eligible_count = len(eligible_ids)

        await session_repo.close_delivery(
            delivery,
            reason=reason.value,
            respondent_count=respondent_count,
            eligible_count=eligible_count,
        )

        await hub.broadcast(
            delivery.session_id,
            ServerEventType.QUESTION_CLOSED,
            {
                "question_id": str(delivery.question_id),
                "reason": reason.value,
                "respondents": respondent_count,
                "eligible": eligible_count,
            },
        )

        if question is not None and question.question_type == "mcq":
            correct_count = await response_repo.correct_count(
                delivery.session_id, delivery.question_id
            )
            decision = evaluate_comprehension_alert(
                respondents=respondent_count,
                correct_count=correct_count,
                min_respondents=min_respondents,
                threshold=alert_threshold,
            )
            if decision.should_alert:
                await hub.broadcast(
                    delivery.session_id,
                    ServerEventType.ALERT_RAISED,
                    {
                        "alert_id": str(uuid.uuid4()),
                        "kind": AlertKind.TOPIC_DIFFICULTY.value,
                        "message": (
                            f"Only {decision.correct_ratio:.0%} of respondents answered "
                            f"correctly on '{question.topic or question.question_text[:60]}'."
                        ),
                        "reason": (
                            f"{correct_count}/{respondent_count} correct, below the "
                            f"{alert_threshold:.0%} threshold with at least "
                            f"{min_respondents} respondents."
                        ),
                        "confidence": min(1.0, respondent_count / max(min_respondents, 1) / 2),
                    },
                )


async def _only_students(db, user_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Map participant user ids down to student ids for missed_response rows.

    Participants include the lecturer, who is never "missing" an answer.
    """
    from sqlalchemy import select

    from app.models.student import Student

    if not user_ids:
        return set()
    result = await db.execute(select(Student.student_id).where(Student.user_id.in_(user_ids)))
    return set(result.scalars().all())


def _closes_at_iso(window_seconds: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=window_seconds)).isoformat()


lifecycle = SessionLifecycle()
