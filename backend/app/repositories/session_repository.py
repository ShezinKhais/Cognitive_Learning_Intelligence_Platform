"""Database queries for live sessions, participants and delivered questions.

Owner: BBIS, Phase 3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.question import Question
from app.models.session import Session as SessionModel
from app.models.session_participant import SessionParticipant

# A live session moves through a small state machine. Ending or cancelling is
# terminal: a session that has finished cannot be reopened by resubmitting a
# start request, and pause/resume was never part of Phase 3's frozen contract
# (the SessionStatus enum has no PAUSED value), so "pause" in the PHASES.md
# deliverable is read as "the lecturer stops triggering questions", not as a
# distinct persisted state.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "prepared": {"prepared", "active", "cancelled"},
    "active": {"ending", "ended", "cancelled"},
    "ending": {"ended"},
    "ended": set(),
    "cancelled": set(),
}


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        instructor_id: uuid.UUID,
        course_id: uuid.UUID,
        title: str,
        starts_at: datetime | None,
    ) -> SessionModel:
        now = starts_at or datetime.now(UTC)
        row = SessionModel(
            instructor_id=instructor_id,
            course_id=course_id,
            title=title,
            start_time=now,
            end_time=now,
            mode="online",
            status="prepared",
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_by_id(self, session_id: uuid.UUID) -> SessionModel | None:
        return await self.session.get(SessionModel, session_id)

    async def get_with_course_code(self, session_id: uuid.UUID) -> tuple[SessionModel, str] | None:
        result = await self.session.execute(
            select(SessionModel, Course.code)
            .join(Course, SessionModel.course_id == Course.id)
            .where(SessionModel.session_id == session_id)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        instructor_id: uuid.UUID | None,
        participant_user_id: uuid.UUID | None,
    ) -> tuple[list[tuple[SessionModel, str]], int]:
        """Sessions visible to the caller, newest first.

        An admin passes both filters as None and sees everything. A lecturer
        is scoped to sessions they instruct. A student is scoped to sessions
        they have joined at least once -- a course enrolment alone would leak
        sessions a student's class never actually held.
        """
        query = select(SessionModel, Course.code).join(Course, SessionModel.course_id == Course.id)
        count_query = select(func.count()).select_from(SessionModel)

        if instructor_id is not None:
            query = query.where(SessionModel.instructor_id == instructor_id)
            count_query = count_query.where(SessionModel.instructor_id == instructor_id)

        if participant_user_id is not None:
            participant_sessions = select(SessionParticipant.session_id).where(
                SessionParticipant.user_id == participant_user_id
            )
            query = query.where(SessionModel.session_id.in_(participant_sessions))
            count_query = count_query.where(SessionModel.session_id.in_(participant_sessions))

        total = (await self.session.execute(count_query)).scalar_one()

        result = await self.session.execute(
            query.order_by(SessionModel.start_time.desc(), SessionModel.session_id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1]) for row in result.all()], total

    async def transition(self, row: SessionModel, *, status: str) -> SessionModel:
        allowed = _ALLOWED_TRANSITIONS.get(row.status, set())
        if status not in allowed:
            raise ConflictError(
                f"Cannot move a session from '{row.status}' to '{status}'.",
                {"current_status": row.status, "requested_status": status},
            )
        row.status = status
        if status in {"ended", "cancelled"}:
            row.end_time = datetime.now(UTC)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def has_staged_question(self, session_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(Question)
            .where(Question.session_id == session_id, Question.status == "staged")
        )
        return result.scalar_one() > 0

    async def next_staged_question(self, session_id: uuid.UUID) -> Question | None:
        result = await self.session.execute(
            select(Question)
            .where(Question.session_id == session_id, Question.status == "staged")
            .order_by(Question.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    # --- Participants -----------------------------------------------------

    async def record_join(self, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
        existing = await self.session.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
                SessionParticipant.left_at.is_(None),
            )
        )
        if existing.scalar_one_or_none() is not None:
            return  # already an active participant, e.g. a second tab

        self.session.add(
            SessionParticipant(
                session_id=session_id,
                user_id=user_id,
                joined_at=datetime.now(UTC),
            )
        )
        await self.session.flush()

    async def record_leave(self, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
        result = await self.session.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
                SessionParticipant.left_at.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        row.left_at = datetime.now(UTC)
        self.session.add(row)
        await self.session.flush()

    async def active_participant_ids(self, session_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(SessionParticipant.user_id).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.left_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def participant_count(self, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(SessionParticipant)
            .where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.left_at.is_(None),
            )
        )
        return result.scalar_one()

    async def is_participant(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(SessionParticipant)
            .where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        return result.scalar_one() > 0

    # --- Delivered questions ------------------------------------------------

    async def record_delivery(
        self,
        *,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        window_seconds: int,
    ) -> DeliveredQuestion:
        row = DeliveredQuestion(
            session_id=session_id,
            question_id=question_id,
            delivered_at=datetime.now(UTC),
            window_seconds=window_seconds,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_open_delivery(self, session_id: uuid.UUID) -> DeliveredQuestion | None:
        result = await self.session.execute(
            select(DeliveredQuestion)
            .where(
                DeliveredQuestion.session_id == session_id,
                DeliveredQuestion.closed_at.is_(None),
            )
            .order_by(DeliveredQuestion.delivered_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_delivery(self, delivery_id: uuid.UUID) -> DeliveredQuestion | None:
        return await self.session.get(DeliveredQuestion, delivery_id)

    async def close_delivery(
        self,
        row: DeliveredQuestion,
        *,
        reason: str,
        respondent_count: int,
        eligible_count: int,
    ) -> DeliveredQuestion:
        row.closed_at = datetime.now(UTC)
        row.close_reason = reason
        row.respondent_count = respondent_count
        row.eligible_count = eligible_count
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def count_delivered(self, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DeliveredQuestion)
            .where(DeliveredQuestion.session_id == session_id)
        )
        return result.scalar_one()
