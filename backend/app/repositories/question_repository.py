"""Database queries for questions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.question import Question
from app.models.session import Session as SessionModel

# The contract's own docstring on QuestionStatus says delivery only ever
# happens from STAGED, so nothing reaches a class without a lecturer
# approving it first. That promise is only real if the write path enforces
# it -- without this table, apply_review wrote whatever status the client
# sent, including draft -> delivered directly, or re-approving a question
# that was already delivered (silently changing what counts as the correct
# answer for students who already responded).
#
# Each key is a starting status; the value is the set of statuses that are
# a valid move from there. A transition not listed (including staying in
# the same status, other than draft -> draft edits) is rejected.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"draft", "approved", "rejected"},
    "approved": {"approved", "rejected", "staged"},
    "rejected": {"rejected"},
    "staged": {"staged", "delivered"},
    "delivered": set(),  # terminal: a delivered question is never rewritten
}


class QuestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        return await self.session.get(Question, question_id)

    async def get_with_owner(
        self, question_id: uuid.UUID, *, material_id: uuid.UUID | None = None
    ) -> tuple[Question, uuid.UUID] | None:
        """Question plus the instructor_id that owns its session, in one query.

        The review routes need both: the question to act on, and the owning
        lecturer's id to check against the caller. Doing this as a join
        avoids a second round trip per request and avoids the TOCTOU gap of
        fetching the question, then separately fetching its session.

        material_id, when given, scopes the lookup so a question only
        resolves when it actually belongs to that material -- otherwise a
        lecturer could act on any question by ID through any material's
        URL, regardless of which material the UI navigated them to.
        """
        conditions = [Question.question_id == question_id]
        if material_id is not None:
            conditions.append(Question.source_material_id == material_id)

        result = await self.session.execute(
            select(Question, SessionModel.instructor_id)
            .join(SessionModel, Question.session_id == SessionModel.session_id)
            .where(*conditions)
        )
        row = result.first()
        if row is None:
            return None
        return row[0], row[1]

    async def list_by_ids_with_owner(
        self, question_ids: list[uuid.UUID], *, material_id: uuid.UUID | None = None
    ) -> list[tuple[Question, uuid.UUID]]:
        """Same shape as get_with_owner, for the bulk-review route.

        Returns only the questions that actually exist (and, when
        material_id is given, actually belong to it); the caller is
        responsible for checking which requested ids came back missing.
        """
        if not question_ids:
            return []
        conditions = [Question.question_id.in_(question_ids)]
        if material_id is not None:
            conditions.append(Question.source_material_id == material_id)

        result = await self.session.execute(
            select(Question, SessionModel.instructor_id)
            .join(SessionModel, Question.session_id == SessionModel.session_id)
            .where(*conditions)
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
            select(func.count())
            .select_from(Question)
            .where(Question.source_material_id == material_id)
        )
        return result.scalar_one()

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

        Raises ConflictError if the requested status is not a valid move
        from the question's current status (see _ALLOWED_TRANSITIONS), or
        if any edit fields are supplied for a question that is already
        staged or delivered -- once a question has been staged for
        delivery, silently changing its prompt or correct_option would
        change what past or in-flight student responses meant without
        anyone knowing.
        """
        current = question.status
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if status not in allowed:
            raise ConflictError(
                f"Cannot move a question from '{current}' to '{status}'.",
                {"current_status": current, "requested_status": status},
            )

        editing = prompt is not None or options is not None or correct_option is not None
        if editing and current in {"staged", "delivered"}:
            raise ConflictError(
                f"Cannot edit a question that is already '{current}'.",
                {"current_status": current},
            )

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
