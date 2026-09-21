"""Live-session recorder that plugs into General CS's ResponseRecorder seam.

Built against a structural copy of ResponseRecorder's contract (PR #103,
Shezin-Phase-3) rather than importing it, since that branch isn't merged
yet. Once it is, `classroom.recorder` is set to a LiveResponseRecorder
built with the real QuestionRepository.get_by_id and hub.send_to_user.

Persistence belongs to BBIS; this only scores and publishes feedback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.core.errors import NotFoundError
from app.models.question import Question
from app.schemas.events import FeedbackResultPayload
from app.services.response_processing import process_submission


class AnswerSubmission(Protocol):
    """Structural match for General CS's Submission dataclass (PR #103)."""

    session_id: UUID
    question_id: UUID
    user_id: UUID
    selected_option: int | None
    free_text: str | None


GetQuestion = Callable[[UUID], Awaitable[Question | None]]
PublishFeedback = Callable[[UUID, UUID, FeedbackResultPayload], Awaitable[None]]


class LiveResponseRecorder:
    """Scores one accepted live-session answer and publishes its feedback.

    Matches ResponseRecorder.record(submission) -> None structurally:
    raising refuses the answer, per that contract.
    """

    def __init__(self, *, get_question: GetQuestion, publish_feedback: PublishFeedback) -> None:
        self._get_question = get_question
        self._publish_feedback = publish_feedback

    async def record(self, submission: AnswerSubmission) -> None:
        question = await self._get_question(submission.question_id)
        if question is None:
            raise NotFoundError("Question not found.", {"question_id": str(submission.question_id)})

        feedback = process_submission(
            session_id=submission.session_id,
            question=question,
            selected_option=submission.selected_option,
            free_text=submission.free_text,
        )
        await self._publish_feedback(submission.session_id, submission.user_id, feedback)
