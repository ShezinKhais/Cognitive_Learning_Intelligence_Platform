"""MCQ scoring and source-grounded feedback.

MCQ scoring is deterministic: the student's selected option is compared with
the lecturer-approved question's stored correct_option. The result also keeps
the source slide/page and excerpt produced and validated during Phase 2 so the
student can receive feedback grounded in the lecturer's own material.

Free-text classification is deliberately not implemented here. Phase 5 will
provide that classifier through a separate path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.errors import ValidationError
from app.models.question import Question
from app.schemas.events import FeedbackResultPayload


@dataclass(frozen=True)
class MCQScoreResult:
    """The result of scoring one multiple-choice response."""

    is_correct: bool
    selected_option: int
    correct_option: int
    correct_answer: str
    source_slide: int | None
    source_excerpt: str | None


@dataclass(frozen=True)
class FeedbackResult:
    """Student-facing feedback grounded in the approved source material."""

    is_correct: bool
    message: str
    source_slide: int | None
    source_excerpt: str | None


class FreeTextClassifier(Protocol):
    """Interface reserved for later free-text comprehension classification."""

    async def classify(
        self,
        *,
        question: Question,
        answer: str,
    ) -> tuple[str, float, str | None]:
        """Return label, confidence, and optional reason."""
        ...


def score_mcq(question: Question, selected_option: int) -> MCQScoreResult:
    """Score one answer against an approved multiple-choice question."""

    if question.question_type != "mcq":
        raise ValidationError(
            "This scorer only accepts multiple-choice questions.",
            {"question_type": question.question_type},
        )

    if not question.options:
        raise ValidationError(
            "This question has no answer options.",
            {"question_id": str(question.question_id)},
        )

    if question.correct_option is None:
        raise ValidationError(
            "This question has no correct answer configured.",
            {"question_id": str(question.question_id)},
        )

    if not 0 <= question.correct_option < len(question.options):
        raise ValidationError(
            "This question has an invalid correct answer.",
            {
                "question_id": str(question.question_id),
                "correct_option": question.correct_option,
                "options_count": len(question.options),
            },
        )

    if isinstance(selected_option, bool) or not isinstance(selected_option, int):
        raise ValidationError(
            "Selected option must be an integer.",
            {"selected_option": selected_option},
        )

    if not 0 <= selected_option < len(question.options):
        raise ValidationError(
            "Selected option is outside the available choices.",
            {
                "selected_option": selected_option,
                "options_count": len(question.options),
            },
        )

    return MCQScoreResult(
        is_correct=selected_option == question.correct_option,
        selected_option=selected_option,
        correct_option=question.correct_option,
        correct_answer=question.options[question.correct_option],
        source_slide=question.source_slide,
        source_excerpt=question.source_excerpt,
    )


# End of validation checks for the question before scoring
def build_mcq_feedback(result: MCQScoreResult) -> FeedbackResult:
    """Build immediate source-grounded feedback from an MCQ score.

    Withholds the correct answer: this goes out while the response window
    may still be open, and the first wrong answer would otherwise leak the
    answer to the rest of the class. Use build_mcq_reveal once the question
    has closed.
    """

    status = "Correct" if result.is_correct else "Incorrect"
    if result.source_slide is not None:
        message = f"{status}. See slide/page {result.source_slide} for the supporting material."
    else:
        message = f"{status}."

    return FeedbackResult(
        is_correct=result.is_correct,
        message=message,
        source_slide=result.source_slide,
        source_excerpt=result.source_excerpt,
    )


def build_mcq_reveal(result: MCQScoreResult) -> FeedbackResult:
    """Build the answer-reveal feedback sent after the question has closed."""

    if result.source_slide is not None:
        message = (
            f"The correct answer is '{result.correct_answer}'. "
            f"See slide/page {result.source_slide} for the supporting material."
        )
    else:
        message = f"The correct answer is '{result.correct_answer}'."

    return FeedbackResult(
        is_correct=result.is_correct,
        message=message,
        source_slide=result.source_slide,
        source_excerpt=result.source_excerpt,
    )


def feedback_payload(
    question_id: UUID,
    feedback: FeedbackResult,
) -> FeedbackResultPayload:
    """Convert internal grounded feedback to the frozen live-event contract."""

    return FeedbackResultPayload(
        question_id=question_id,
        correct=feedback.is_correct,
        explanation=feedback.message,
        source_slide=feedback.source_slide,
    )
