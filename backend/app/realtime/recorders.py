"""What a live session hands to the workstreams that store and score it.

Owner: General CS, Phase 3, for the contract. AI 1 and BBIS provide the
implementations and register them on the classroom.

Scoring and storing answers, question closes and prompt outcomes plug in
through ResponseRecorder, CloseRecorder and PromptRecorder. Until one is set,
an accepted answer is counted towards the question's respondents and kept
nowhere else; Classroom.check_wiring() says so at startup, and refuses to
start in production.

Recorders are called concurrently, one call per answer, close or prompt, so
an implementation must not share one database session between calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.schemas.events import FeedbackResultPayload, QuestionCloseReason

# A recorder that stops answering must not leave a student with no receipt,
# or an ended session waiting on a prompt outcome.
RECORD_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Submission:
    """One accepted answer, as handed to the recorder."""

    session_id: UUID
    question_id: UUID
    user_id: UUID
    selected_option: int | None
    free_text: str | None
    client_elapsed_ms: int
    received_at: datetime


class ResponseRecorder(Protocol):
    """Stores and scores an accepted answer. BBIS and AI 1 provide this.

    Raising, or taking longer than RECORD_TIMEOUT_SECONDS, refuses the answer:
    the student is told it was not saved and may submit again while the
    window is open. A slow write may still land after that, so storing must
    be idempotent per question and student.

    What it returns is sent to the student as feedback.result, after the
    receipt accepting the answer. None sends nothing. The recorder must not
    send feedback itself, since until it returns the answer can still be
    refused.
    """

    async def record(self, submission: Submission) -> FeedbackResultPayload | None: ...


@dataclass(frozen=True)
class ClosedQuestion:
    """How one delivered question ended, as handed to the close recorder."""

    session_id: UUID
    question_id: UUID
    reason: QuestionCloseReason
    closed_at: datetime
    # Students who were shown it, and those whose answer was accepted.
    eligible: frozenset[UUID]
    answered: frozenset[UUID]


class CloseRecorder(Protocol):
    """Stores how a question ended, and may reveal its answer. BBIS and AI 1
    provide this.

    It runs after question.closed has gone out, so the window is over and the
    answer can be shown. A failure is logged and otherwise ignored: the class
    has already moved on.
    """

    async def record_close(self, closed: ClosedQuestion) -> None: ...


class PromptResult(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PromptOutcome:
    """How one attention prompt ended, as handed to the prompt recorder."""

    session_id: UUID
    prompt_id: UUID
    user_id: UUID
    escalation: int
    sent_at: datetime
    expires_at: datetime
    result: PromptResult
    responded_at: datetime | None


class PromptRecorder(Protocol):
    """Stores prompt outcomes for the engagement record. BBIS provides this.

    A failure is logged and otherwise ignored: the student has already seen
    the prompt, and nothing they could do would change what happened.
    """

    async def record_prompt(self, outcome: PromptOutcome) -> None: ...
