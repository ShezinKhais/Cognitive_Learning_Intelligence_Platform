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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import ConflictError, ValidationError
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.repositories.question_repository import validate_question_shape
from app.schemas.content import QuestionCreateRequest, QuestionStatus, QuestionType
from app.services.material_edits import owned_material


async def write_question(
    db: AsyncSession, principal: Principal, material_id: UUID, payload: QuestionCreateRequest
) -> Question:
    """A lecturer's own question for one of their materials, ready to send."""
    material = await owned_material(db, principal, material_id)
    if material.status != "completed":
        raise ConflictError(
            "Choose a processed material, or retry processing it before adding questions."
        )
    excerpt = (payload.source_excerpt or "").strip() or None
    if payload.source_slide is not None or excerpt:
        locator = select(RagChunk.chunk_id).where(RagChunk.source_material_id == material_id)
        if payload.source_slide is not None:
            locator = locator.where(RagChunk.source_page == payload.source_slide)
        if excerpt:
            locator = locator.where(RagChunk.chunk_text.contains(excerpt, autoescape=True))
        if await db.scalar(locator.limit(1)) is None:
            raise ValidationError(
                "The source does not match an indexed passage in this material.",
                {"field": "source_excerpt"},
            )
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
        source_slide=payload.source_slide,
        source_excerpt=excerpt,
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
    validate_reusable(question)
    row = copy_question(question, principal.user_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def validate_reusable(question: Question) -> None:
    """Do not turn a malformed historical question into a new live checkpoint."""
    validate_question_shape(question.question_text, question.options, question.correct_option)
    if question.question_type == QuestionType.MCQ.value:
        if question.correct_option is None or not question.options:
            raise ValidationError("An MCQ needs choices and a correct answer.")
    elif not (question.reference_answer or "").strip() or not any(
        point.strip() for point in question.key_points or []
    ):
        raise ValidationError("A written question needs a reference answer and key points.")


def copy_question(question: Question, reviewer_id: UUID) -> Question:
    """No history or session binding is copied; the caller owns the transaction."""
    return Question(
        source_material_id=question.source_material_id,
        source_question_id=question.source_question_id or question.question_id,
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
        reviewed_by=reviewer_id,
        reviewed_at=datetime.now(UTC),
    )
