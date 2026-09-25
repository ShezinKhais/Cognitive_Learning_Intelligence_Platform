"""What a live session hands to the workstreams that store and score it.

Owner: General CS, Phase 3, for the contract. AI 1, BBIS and Cyber 1 provide
the implementations, and app/services/live_wiring.py registers them on the
classroom at startup.

Storing and scoring answers, question closes, prompt outcomes and
attendance plug in through ResponseRecorder, CloseRecorder, PromptRecorder and
ParticipantRecorder, and the class comprehension alert reads through
ComprehensionSource. Until one is set, an
accepted answer is counted towards the question's respondents and kept
nowhere else; Classroom.check_wiring() says so at startup, and refuses to
start in production.

Recorders are called concurrently, one call per answer, close, prompt or
socket, so an implementation must not share one database session between
calls.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from app.schemas.events import FeedbackResultPayload, QuestionCloseReason

log = logging.getLogger("clip.classroom")

# A recorder that stops answering must not leave a student with no receipt,
# or an ended session waiting on a prompt outcome.
RECORD_TIMEOUT_SECONDS = 5.0

T = TypeVar("T")


async def best_effort(call: Awaitable[T], what: str, session_id: UUID) -> T | None:
    """Run a recorder or source whose failure changes nothing for the class.

    Bounded by RECORD_TIMEOUT_SECONDS, logged if it fails, and None then.
    Answers are the exception: a failed answer is refused, so the classroom
    calls that recorder itself.
    """
    try:
        async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
            return await call
    except Exception:
        log.exception("could not %s in session %s", what, session_id)
        return None


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

    The delivery it completes was recorded with the claim that delivered
    the question, in the same transaction, so it is always there to update.
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


@dataclass(frozen=True)
class Attendance:
    """One student arriving in, or leaving, a live session."""

    session_id: UUID
    user_id: UUID
    at: datetime


class ParticipantRecorder(Protocol):
    """Stores who attended a live session. BBIS provides this.

    A student may have several tabs open. record_join is called for each
    socket, since reconnecting belongs in the attendance record, but
    record_leave only once the last of them has closed: a student who closes
    one tab has not left the class. A failure is logged and otherwise ignored.
    """

    async def record_join(self, joined: Attendance) -> None: ...

    async def record_leave(self, left: Attendance) -> None: ...


@dataclass(frozen=True)
class QuestionComprehension:
    """The comprehension labels AI 1 has recorded for one delivered question."""

    labels: list[str]
    topic: str | None


class ComprehensionSource(Protocol):
    """Reads the classifications behind a class comprehension alert. Cyber 1
    provides this."""

    async def question_labels(
        self, session_id: UUID, question_id: UUID
    ) -> QuestionComprehension: ...
