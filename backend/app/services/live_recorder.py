"""AI 1's recorders for the live classroom's ResponseRecorder and
CloseRecorder seams.

live_wiring.py registers both at startup, built on QuestionRepository and
BBIS's LiveEventRepository, each call in its own committed session.

LiveResponseRecorder scores, stores, then returns the feedback. It never
sends the feedback itself: the classroom sends it as feedback.result after
the receipt accepting the answer, so a student never sees a result for a
refused answer. That feedback withholds the correct answer, since the window
is still open for the rest of the class.

LiveCloseRecorder stores how the question ended, then reveals the correct
answer to each student who answered, now that the window is over.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.core.errors import NotFoundError, ValidationError
from app.models.question import Question
from app.realtime.classroom import ClosedQuestion, PromptOutcome, Submission
from app.schemas.content import QuestionType
from app.schemas.events import FeedbackResultPayload
from app.services.response_processing import process_submission
from app.services.scoring import build_mcq_reveal, feedback_payload, score_mcq

log = logging.getLogger("clip.live_recorder")


class StoredResponse(Protocol):
    """The answer as stored, matching BBIS's StudentResponse."""

    selected_option: int | None
    free_text: str | None


class StoreResponse(Protocol):
    """Matches LiveEventRepository.record_response.

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

# Stores how a question ended; LiveEventRepository.close_question_delivery.
StoreClose = Callable[[ClosedQuestion], Awaitable[object]]

# The stored answers to one question, by user id; answers_to_question.
GetAnswers = Callable[[UUID, UUID], Awaitable[Mapping[UUID, StoredResponse]]]

# Sends one student a feedback.result.
SendFeedback = Callable[[UUID, UUID, FeedbackResultPayload], Awaitable[object]]


class LiveResponseRecorder:
    """Scores and stores one accepted live-session answer.

    Matches ResponseRecorder.record(submission) -> FeedbackResultPayload | None
    structurally: raising refuses the answer, per that contract.
    """

    def __init__(self, *, get_question: GetQuestion, store_response: StoreResponse) -> None:
        self._get_question = get_question
        self._store_response = store_response

    async def record(self, submission: Submission) -> FeedbackResultPayload:
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


class LiveCloseRecorder:
    """Stores a question's close, then reveals its answer.

    Matches CloseRecorder.record_close(closed) structurally. It runs after
    question.closed has gone out, so the answer can no longer help anyone
    still answering.
    """

    def __init__(
        self,
        *,
        get_question: GetQuestion,
        store_close: StoreClose,
        get_answers: GetAnswers,
        send_feedback: SendFeedback,
    ) -> None:
        self._get_question = get_question
        self._store_close = store_close
        self._get_answers = get_answers
        self._send_feedback = send_feedback

    async def record_close(self, closed: ClosedQuestion) -> None:
        # Stored first: the record matters more than the reveal.
        await self._store_close(closed)

        question = await self._get_question(closed.question_id)
        if question is None or question.question_type != QuestionType.MCQ:
            # Free text has no single correct answer to reveal.
            return

        answers = await self._get_answers(closed.session_id, closed.question_id)
        reveals = []
        # Only students the classroom accepted an answer from. A write that
        # timed out can still land, but that student was told it was not
        # saved, so a result for it would contradict what they saw.
        for user_id in closed.answered:
            stored = answers.get(user_id)
            if stored is None or stored.selected_option is None:
                continue
            try:
                score = score_mcq(question, stored.selected_option)
            except ValidationError:
                log.warning("could not reveal question %s to user %s", closed.question_id, user_id)
                continue
            payload = feedback_payload(question.question_id, build_mcq_reveal(score))
            reveals.append(self._send_feedback(closed.session_id, user_id, payload))
        # Together, so one slow socket does not hold up the rest of the class.
        await asyncio.gather(*reveals)


class StorePromptOutcome(Protocol):
    """Matches LiveEventRepository.record_prompt_outcome."""

    def __call__(
        self,
        *,
        prompt_id: UUID,
        session_id: UUID,
        user_id: UUID,
        escalation: int,
        sent_at: datetime,
        expires_at: datetime,
        result: str,
        responded_at: datetime | None,
    ) -> Awaitable[object]: ...


class LivePromptRecorder:
    """Stores one attention-prompt outcome.

    Matches PromptRecorder.record_prompt(outcome) -> None structurally.
    """

    def __init__(self, *, store_prompt_outcome: StorePromptOutcome) -> None:
        self._store_prompt_outcome = store_prompt_outcome

    async def record_prompt(self, outcome: PromptOutcome) -> None:
        await self._store_prompt_outcome(
            prompt_id=outcome.prompt_id,
            session_id=outcome.session_id,
            user_id=outcome.user_id,
            escalation=outcome.escalation,
            sent_at=outcome.sent_at,
            expires_at=outcome.expires_at,
            result=outcome.result,
            responded_at=outcome.responded_at,
        )
