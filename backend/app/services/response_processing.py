"""Processing for accepted live-session responses.

This module connects the live-session submission flow to AI 1's scoring
service without owning persistence or changing the frozen WebSocket contract.

Persistence belongs to BBIS. The live-session ResponseRecorder integration
will be added after the General CS Phase 3 hook is merged.
"""

from uuid import UUID

from app.core.errors import ValidationError
from app.models.question import Question
from app.schemas.content import QuestionStatus
from app.schemas.events import FeedbackResultPayload
from app.services.scoring import (
    build_mcq_feedback,
    feedback_payload,
    score_mcq,
)


def process_mcq_submission(
    *,
    session_id: UUID,
    question: Question,
    selected_option: int,
) -> FeedbackResultPayload:
    """Score one accepted live-session MCQ and build instant feedback.

    The live-session layer is responsible for deciding whether the response
    arrived within the response window. This function verifies that the
    question actually belongs to that session and has been delivered, then
    delegates scoring and feedback construction to the scoring service.
    """

    if question.session_id != session_id:
        raise ValidationError(
            "Question does not belong to this live session.",
            {
                "question_id": str(question.question_id),
                "session_id": str(session_id),
            },
        )

    if question.status != QuestionStatus.DELIVERED.value:
        raise ValidationError(
            "Only a delivered question can be scored for a live session.",
            {
                "question_id": str(question.question_id),
                "question_status": question.status,
            },
        )

    score = score_mcq(question, selected_option)
    feedback = build_mcq_feedback(score)

    return feedback_payload(question.question_id, feedback)
