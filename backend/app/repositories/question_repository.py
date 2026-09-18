"""Database queries for questions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationError
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


def _validate_option_shape(
    current_options: list[str] | None,
    new_options: list[str] | None,
    current_correct_option: int | None,
    new_correct_option: int | None,
) -> None:
    """Check that the option list and correct_option that will actually be
    stored after this edit agree with each other.

    Checked against the values that will be written after the edit, not
    just the values the caller supplied: options alone can shrink below an
    existing correct_option even when correct_option itself isn't part of
    this request, and correct_option alone can point past the end of the
    existing options list. Either combination, once written, is an answer
    key that points at nothing.
    """
    effective_options = new_options if new_options is not None else current_options
    effective_correct = (
        new_correct_option if new_correct_option is not None else current_correct_option
    )

    if effective_correct is None:
        return  # free-text questions have no options to check against

    if not effective_options or not (0 <= effective_correct < len(effective_options)):
        raise ValidationError(
            "correct_option must be a valid index into options.",
            {
                "options_count": len(effective_options) if effective_options else 0,
                "correct_option": effective_correct,
            },
        )


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

    async def list_owned_by_material(
        self,
        material_id: uuid.UUID,
        principal_user_id: uuid.UUID,
        *,
        is_admin: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Question], int]:
        """Questions for a material, scoped to what the caller may see.

        An admin sees every question for the material. A lecturer sees only
        the ones whose session they are the instructor of -- a material can
        in principle carry sessions taught by more than one lecturer, and
        QuestionOut includes correct_option, which must never reach a caller
        who isn't the question's own reviewer or an admin. Returns
        (questions, total) so the caller can build a Page without a second
        round trip for the count.
        """
        conditions = [Question.source_material_id == material_id]
        if not is_admin:
            conditions.append(SessionModel.instructor_id == principal_user_id)

        count_result = await self.session.execute(
            select(func.count())
            .select_from(Question)
            .join(SessionModel, Question.session_id == SessionModel.session_id)
            .where(*conditions)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Question)
            .join(SessionModel, Question.session_id == SessionModel.session_id)
            .where(*conditions)
            .order_by(Question.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

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

        Raises ValidationError if the options/correct_option that will
        actually be stored after this edit don't agree with each other
        (see _validate_option_shape) -- an out-of-range correct_option, or
        an options list shrunk below an existing correct_option, would
        otherwise silently save an answer key that points at nothing.
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

        _validate_option_shape(question.options, options, question.correct_option, correct_option)

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
