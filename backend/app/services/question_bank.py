"""Questions a lecturer adds by hand or asks again.

A generated question is used once: delivering it claims it for that session.
Next term's class would otherwise need the same deck uploaded and reviewed
again, so a delivered question can be reused, which stages a copy, and a
lecturer can write a question of their own for a material.

Both are staged straight away. Writing a question, or choosing to ask one
again, is the lecturer's approval, as approving a draft is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import ConflictError, ValidationError
from app.models.question import Question
from app.repositories.question_repository import validate_question_shape
from app.schemas.content import QuestionCreateRequest, QuestionStatus, QuestionType
from app.services.material_edits import owned_material


async def write_question(
    db: AsyncSession, principal: Principal, material_id: UUID, payload: QuestionCreateRequest
) -> Question:
    """A lecturer's own question for one of their materials, ready to send."""
    await owned_material(db, principal, material_id)
    prompt = payload.prompt.strip()
    if payload.type == QuestionType.MCQ:
        if payload.options is None or payload.correct_option is None:
            raise ValidationError(
                "A multiple choice question needs options and the correct one.", {}
            )
        options = [option.strip() for option in payload.options]
        correct = payload.correct_option
        reference, points = None, None
    else:
        options, correct = None, None
        # Without both, a written answer is never marked: free_text_marking
        # needs them to compare an answer against.
        reference = (payload.reference_answer or "").strip()
        points = [point.strip() for point in payload.key_points or [] if point.strip()]
        if not reference or not points:
            raise ValidationError(
                "A written-answer question needs a model answer and at least one key point, "
                "so answers to it can be marked.",
                {"field": "reference_answer"},
            )
    validate_question_shape(prompt, options, correct)
    row = Question(
        source_material_id=material_id,
        session_id=None,
        question_text=prompt,
        question_type=payload.type.value,
        status=QuestionStatus.STAGED.value,
        difficulty=payload.difficulty.value,
        options=options,
        correct_option=correct,
        topic=(payload.topic or "").strip() or None,
        reference_answer=reference,
        key_points=points,
        reviewed_by=principal.user_id,
        reviewed_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def reuse_question(db: AsyncSession, principal: Principal, question: Question) -> Question:
    """Stage a copy of a delivered question for the lecturer's next class.
    The original stays with the session that asked it, with its answers."""
    if question.status != QuestionStatus.DELIVERED.value:
        raise ConflictError(
            "Only a question that has been asked can be reused. This one can still be sent.",
            {"current_status": question.status},
        )
    row = Question(
        source_material_id=question.source_material_id,
        session_id=None,
        question_text=question.question_text,
        question_type=question.question_type,
        status=QuestionStatus.STAGED.value,
        difficulty=question.difficulty,
        options=list(question.options) if question.options is not None else None,
        correct_option=question.correct_option,
        topic=question.topic,
        source_slide=question.source_slide,
        source_excerpt=question.source_excerpt,
        reference_answer=question.reference_answer,
        key_points=list(question.key_points) if question.key_points is not None else None,
        reviewed_by=principal.user_id,
        reviewed_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
