"""Records AI 1's comprehension label for a scored live answer.

Owner: AI 1, Phase 3. Cyber 1's DatabaseComprehensionSource reads these rows
for the class comprehension alert; without them the alert has nothing to
count and can never fire.

Only multiple-choice answers are labelled here. A right answer is mastered
and a wrong one struggling: a single choice has no partial credit, so partial
is left for Phase 5's free-text classifier, which is also when free-text
answers start getting a label at all.

The label is written in the same transaction as the answer it describes, so
the two are stored together or not at all. That keeps it inside the answer's
own write rather than a second one sharing the recorder's time budget, and
the close, which waits for each answer's write, always finds it.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comprehension_result import ComprehensionResult
from app.models.student_response import StudentResponse
from app.schemas.session import ComprehensionLabel

# An MCQ answer is scored against its stored correct option, not estimated.
MCQ_CONFIDENCE = 1.0


def mcq_label(correct: bool) -> ComprehensionLabel:
    return ComprehensionLabel.MASTERED if correct else ComprehensionLabel.STRUGGLING


async def label_response(db: AsyncSession, response: StudentResponse) -> None:
    """Add the label for a stored answer to the caller's transaction.

    Labels the answer as stored, not as resubmitted: a retry is handed back
    the answer already kept, and the label must describe that one. A response
    already labelled keeps its label, which the unique response_id enforces
    even for two writes at once.
    """
    if response.is_correct is None:
        return
    await db.execute(
        insert(ComprehensionResult)
        .values(
            response_id=response.response_id,
            label=mcq_label(response.is_correct).value,
            confidence_score=MCQ_CONFIDENCE,
            score=1.0 if response.is_correct else 0.0,
            # The explanation is sent to the student with the feedback; the
            # column is filled by Phase 5's free-text classifier.
            ai_feedback_text="",
        )
        .on_conflict_do_nothing(index_elements=[ComprehensionResult.response_id])
    )


async def save_classification(
    db: AsyncSession,
    *,
    response_id: UUID,
    label: ComprehensionLabel,
    confidence: float,
    score: float,
    feedback: str,
    model_name: str | None,
    prompt_version: str | None,
    reasons: Sequence[str] = (),
    key_point_coverage: Sequence[str] = (),
    wrong_claim: str | None = None,
    similarity: float | None = None,
) -> bool:
    """Add a classifier's result for a stored answer to the caller's transaction.

    Keeps the model and prompt that produced it, and the reasons behind the
    label, so a result can be compared across versions and explained to the
    lecturer. An answer that already has a result keeps it, as for
    label_response. Returns whether this call stored one.
    """
    stored = await db.scalar(
        insert(ComprehensionResult)
        .values(
            response_id=response_id,
            label=label.value,
            confidence_score=confidence,
            score=score,
            ai_feedback_text=feedback,
            model_name=model_name,
            prompt_version=prompt_version,
            reasons=list(reasons),
            key_point_coverage=list(key_point_coverage),
            wrong_claim=wrong_claim,
            similarity=similarity,
        )
        .on_conflict_do_nothing(index_elements=[ComprehensionResult.response_id])
        .returning(ComprehensionResult.result_id)
    )
    return stored is not None
