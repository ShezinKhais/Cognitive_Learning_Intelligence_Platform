"""Live-session recorder that plugs into General CS's ResponseRecorder seam.

Built against a structural copy of ResponseRecorder's contract (PR #103,
Shezin-Phase-3) rather than importing it, since that branch isn't merged
yet. Once #103 and BBIS's repository (PR #108) are in, `classroom.recorder`
is set to a LiveResponseRecorder built with QuestionRepository.get_by_id and
LiveEventRepository.record_response, each run in its own committed session.

The recorder scores, stores, then returns the feedback. It never sends the
feedback itself: the classroom sends it as feedback.result after the receipt
accepting the answer, so a student never sees a result for a refused answer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
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
    client_elapsed_ms: int
    received_at: datetime


class StoredResponse(Protocol):
    """The answer as stored, matching BBIS's StudentResponse (PR #108)."""

    selected_option: int | None
    free_text: str | None


class StoreResponse(Protocol):
    """Matches LiveEventRepository.record_response (PR #108).

    Idempotent per (session, question, student): storing again returns the
    answer already stored instead of adding a second one.
    """

    def __call__(
        self,
        *,
        session_id: UUID,
        question_id: UUID,
        user_id: UUID,
        selected_option: int | None,
        free_text: str | None,
        is_correct: bool | None,
        elapsed_ms: int | None,
        submitted_at: datetime | None = None,
    ) -> Awaitable[StoredResponse]: ...


GetQuestion = Callable[[UUID], Awaitable[Question | None]]


class LiveResponseRecorder:
    """Scores and stores one accepted live-session answer.

    Matches ResponseRecorder.record(submission) -> FeedbackResultPayload | None
    structurally: raising refuses the answer, per that contract.
    """

    def __init__(self, *, get_question: GetQuestion, store_response: StoreResponse) -> None:
        self._get_question = get_question
        self._store_response = store_response

    async def record(self, submission: AnswerSubmission) -> FeedbackResultPayload:
        question = await self._get_question(submission.question_id)
        if question is None:
            raise NotFoundError("Question not found.", {"question_id": str(submission.question_id)})

        feedback = process_submission(
            session_id=submission.session_id,
            question=question,
            selected_option=submission.selected_option,
            free_text=submission.free_text,
        )

        stored = await self._store_response(
            session_id=submission.session_id,
            question_id=submission.question_id,
            user_id=submission.user_id,
            selected_option=submission.selected_option,
            free_text=submission.free_text,
            is_correct=feedback.correct,
            elapsed_ms=submission.client_elapsed_ms,
            submitted_at=submission.received_at,
        )

        # A write that timed out can still land, so a retry may find an
        # earlier answer already stored. The feedback must match that one.
        if (stored.selected_option, stored.free_text) != (
            submission.selected_option,
            submission.free_text,
        ):
            feedback = process_submission(
                session_id=submission.session_id,
                question=question,
                selected_option=stored.selected_option,
                free_text=stored.free_text,
            )

        return feedback
