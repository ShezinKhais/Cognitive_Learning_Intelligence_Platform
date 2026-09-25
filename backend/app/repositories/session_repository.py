"""Database queries for live sessions and the questions they deliver.

Owner: General CS, Phase 3, for what the session lifecycle needs. BBIS owns
session persistence and the dashboard queries, and is expected to extend this
rather than start a second repository for the same table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.repositories.live_event_repository import LiveEventRepository
from app.schemas.content import QuestionStatus, QuestionType


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        instructor_id: uuid.UUID,
        course_id: uuid.UUID,
        title: str,
        start_time: datetime,
        status: str,
        mode: str,
    ) -> Session:
        row = Session(
            instructor_id=instructor_id,
            course_id=course_id,
            title=title,
            start_time=start_time,
            status=status,
            mode=mode,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get(self, session_id: uuid.UUID, *, for_update: bool = False) -> Session | None:
        """One session. for_update locks the row until the transaction ends, so
        two lifecycle calls on the same session cannot both pass the status
        check."""
        query = select(Session).where(Session.session_id == session_id)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def course_code(self, course_id: uuid.UUID) -> str:
        result = await self.session.execute(select(Course.code).where(Course.id == course_id))
        return result.scalar_one()

    async def count_delivered(self, session_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DeliveredQuestion)
            .where(DeliveredQuestion.session_id == session_id)
        )
        return result.scalar_one()

    def _deliverable(self, live: Session):  # noqa: ANN202 - a select
        """Staged questions this session may deliver.

        A question is staged at review, before any session exists, so it is
        claimed by the session that delivers it. Until then it belongs to
        whichever session of its uploader asks first, as long as the material
        is for this session's course or for no course in particular.
        """
        return (
            select(Question)
            .join(Material, Material.id == Question.source_material_id)
            .where(
                Question.status == QuestionStatus.STAGED.value,
                # A multiple choice question with no choices cannot be
                # answered, so it is not deliverable. Sending it would put a
                # question on every screen that no answer could satisfy.
                or_(
                    Question.question_type != QuestionType.MCQ.value,
                    func.cardinality(Question.options) > 0,
                ),
                or_(
                    Question.session_id == live.session_id,
                    (Question.session_id.is_(None))
                    & (Material.uploaded_by_user_id == live.instructor_id)
                    & or_(Material.course_id.is_(None), Material.course_id == live.course_id),
                ),
            )
        )

    async def has_deliverable(self, live: Session) -> bool:
        result = await self.session.execute(self._deliverable(live).limit(1))
        return result.scalar_one_or_none() is not None

    async def list_deliverable(
        self,
        live: Session,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Question], int]:
        """List staged questions this session may actually deliver."""
        eligible = self._deliverable(live)

        total = (
            await self.session.execute(select(func.count()).select_from(eligible.subquery()))
        ).scalar_one()

        questions = (
            (
                await self.session.execute(
                    eligible.order_by(Question.created_at, Question.question_id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

        return list(questions), total

    async def claim_for_delivery(
        self,
        live: Session,
        question_id: uuid.UUID | None = None,
        *,
        delivered_at: datetime,
        closes_at: datetime,
        window_seconds: int,
    ) -> Question | None:
        """Deliver the next deliverable question, or the named one: mark it
        delivered and record the delivery, in the caller's transaction.

        The two answer different questions and are written together so they
        cannot disagree. The question's status is whether it may still be
        offered; the delivered_question row is the session's record of when
        it went out and, once it closes, who was shown it and who answered.
        That row is what the close recorder completes and what the session's
        count of delivered questions reads.

        Locks the row and skips any another transaction holds, so two sessions
        of the same lecturer cannot both deliver one unassigned question.
        Returns None when there is nothing to deliver.
        """
        query = self._deliverable(live)
        if question_id is not None:
            query = query.where(Question.question_id == question_id)
        query = (
            query.order_by(Question.created_at, Question.question_id)
            .limit(1)
            .with_for_update(of=Question, skip_locked=True)
        )
        question = (await self.session.execute(query)).scalar_one_or_none()
        if question is None:
            return None
        question.session_id = live.session_id
        question.status = QuestionStatus.DELIVERED.value
        await self.session.flush()
        await LiveEventRepository(self.session).record_question_delivery(
            session_id=live.session_id,
            question_id=question.question_id,
            delivered_at=delivered_at,
            closes_at=closes_at,
            window_seconds=window_seconds,
        )
        return question
