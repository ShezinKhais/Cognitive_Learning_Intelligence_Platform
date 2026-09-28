"""Records AI 1's comprehension label for a scored live answer.

Owner: AI 1, Phase 3. Cyber 1's DatabaseComprehensionSource reads these rows
for the class comprehension alert; without them the alert has nothing to
count and can never fire.

Only multiple-choice answers are labelled here. A right answer is mastered
and a wrong one struggling: a single choice has no partial credit, so partial
is left for Phase 5's free-text classifier, which is also when free-text
answers start getting a label at all.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.comprehension_result import ComprehensionResult
from app.schemas.events import FeedbackResultPayload
from app.schemas.session import ComprehensionLabel

# An MCQ answer is scored against its stored correct option, not estimated.
MCQ_CONFIDENCE = 1.0


def mcq_label(correct: bool) -> ComprehensionLabel:
    return ComprehensionLabel.MASTERED if correct else ComprehensionLabel.STRUGGLING


async def store_comprehension(response_id: UUID, feedback: FeedbackResultPayload) -> None:
    """Store the label for one stored answer, once.

    A retried submission comes back with the answer already stored, so the
    label may already exist too. The reader counts a student once either way,
    but a second row would still be a duplicate record of the same answer.
    """
    if feedback.correct is None:
        return

    async with get_session_factory()() as db:
        try:
            existing = await db.scalar(
                select(ComprehensionResult.result_id).where(
                    ComprehensionResult.response_id == response_id
                )
            )
            if existing is not None:
                return

            db.add(
                ComprehensionResult(
                    response_id=response_id,
                    label=mcq_label(feedback.correct).value,
                    confidence_score=MCQ_CONFIDENCE,
                    score=1.0 if feedback.correct else 0.0,
                    ai_feedback_text=feedback.explanation or "",
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
