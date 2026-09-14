"""Database queries for questions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.session import Session as SessionModel


class QuestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        return await self.session.get(Question, question_id)

    async def get_with_owner(self, question_id: uuid.UUID) -> tuple[Question, uuid.UUID] | None:
        """Question plus the instructor_id that owns its session, in one query.

        The review routes need both: the question to act on, and the owning
        lecturer's id to check against the caller. Doing this as a join
        avoids a second round trip per request and avoids the TOCTOU gap of
        fetching the question, then separately fetching its session.
        """
        result = await self.session.execute(
            select(Question, SessionModel.instructor_id)
            .join(SessionModel, Question.session_id == SessionModel.session_id)
            .where(Question.question_id == question_id)
        )
        row = result.first()
        if row is None:
            return None
        return row[0], row[1]

    async def list_by_ids_with_owner(
        self, question_ids: list[uuid.UUID]
    ) -> list[tuple[Question, uuid.UUID]]:
        """Same shape as get_with_owner, for the bulk-review route.

        Returns only the questions that actually exist; the caller is
        responsible for checking which requested ids came back missing.
        """
        if not question_ids:
            return []
        result = await self.session.execute(
            select(Question, SessionModel.instructor_id)
            .join(SessionModel, Question.session_id == SessionModel.session_id)
            .where(Question.question_id.in_(question_ids))
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_by_material(
        self, material_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Question]:
        result = await self.session.execute(
            select(Question)
            .where(Question.source_material_id == material_id)
            .order_by(Question.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_material(self, material_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(Question).where(Question.source_material_id == material_id)
        )
        return len(result.all())

    async def apply_review(
        self,
        question: Question,
        *,
        status: str,
        reviewer_id: uuid.UUID,
        prompt: str | None = None,
        options: list[str] | None = None,
        correct_option: int | None = None,
        difficulty: str | None = None,
    ) -> Question:
        """Mutate a question in place per a review decision and flush.

        Only overwrites fields the caller actually supplied (edit is
        optional on approve/reject -- a lecturer can approve without
        changing anything). status, reviewed_by and reviewed_at always
        update, since every call through here is itself a review action.
        """
        question.status = status
        question.reviewed_by = reviewer_id
        question.reviewed_at = datetime.now(UTC)
        if prompt is not None:
            question.question_text = prompt
        if options is not None:
            question.options = options
        if correct_option is not None:
            question.correct_option = correct_option
        if difficulty is not None:
            question.difficulty = difficulty

        self.session.add(question)
        await self.session.flush()
        await self.session.refresh(question)
        return question
