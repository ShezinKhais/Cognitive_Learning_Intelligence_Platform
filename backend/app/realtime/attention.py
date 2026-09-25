"""What one live session knows about each student's attention.

Owner: General CS, Phase 3, with Cyber 1's engagement evidence.

Which attention prompt is waiting on each student, how many each has been
sent, how far each has escalated and how many questions in a row each has let
pass; and the evidence engagement scoring reads: questions shown and
answered, how quickly, how prompts were answered, and the latest signal from
the student's own device. The classroom decides whether now is a fair time to
prompt, sends the prompt, runs its expiry timer and records its outcome, all
under the session's lock. This keeps the counts and applies the per-student
rules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.realtime.recorders import PromptOutcome, PromptResult
from app.schemas.events import AttentionPromptPayload, AttentionSignalPayload
from app.services.engagement import (
    ATTENTION_SIGNAL_MAX_AGE_SECONDS,
    PROMPT_ACKNOWLEDGED,
    PROMPT_DISMISSED,
    PROMPT_EXPIRED,
    EngagementComputation,
    EngagementInputs,
    compute_engagement,
)

MAX_PROMPT_MESSAGE_LENGTH = 280


def checked_message(message: str) -> str:
    """The message a prompt carries, trimmed. A blank or overlong one is a
    mistake by whoever asked for the prompt."""
    message = message.strip()
    if not message or len(message) > MAX_PROMPT_MESSAGE_LENGTH:
        raise ValueError(f"A prompt message must be 1 to {MAX_PROMPT_MESSAGE_LENGTH} characters")
    return message


@dataclass(slots=True)
class Prompt:
    """One prompt sent to one student."""

    session_id: UUID
    user_id: UUID
    sent_at: datetime
    payload: AttentionPromptPayload
    expiry: asyncio.Task[None] | None = None

    def outcome(self, result: PromptResult, responded_at: datetime | None = None) -> PromptOutcome:
        return PromptOutcome(
            session_id=self.session_id,
            prompt_id=self.payload.prompt_id,
            user_id=self.user_id,
            escalation=self.payload.escalation,
            sent_at=self.sent_at,
            expires_at=self.payload.expires_at,
            result=result,
            responded_at=responded_at,
        )


@dataclass(frozen=True)
class ScoredStudent:
    user_id: UUID
    engagement: EngagementComputation
    scored_at: datetime


@dataclass(slots=True)
class _Student:
    sent: int = 0
    # Prompts in a row the student has not answered with "I'm here". This is
    # the escalation the next prompt carries, less one.
    unanswered: int = 0
    # Questions in a row the student was shown and did not answer.
    missed: int = 0
    waiting: Prompt | None = None
    # Engagement evidence for the whole session, fed to Cyber 1's scoring.
    shown: int = 0
    answered: int = 0
    response_times: list[float] = field(default_factory=list)
    prompt_responses: list[float] = field(default_factory=list)
    signal: AttentionSignalPayload | None = None
    signal_at: datetime | None = None
    score: ScoredStudent | None = None

    def current_signal(self, now: datetime) -> AttentionSignalPayload | None:
        """The latest signal, unless it is too old to describe the student
        now: a camera closed early in the lecture must not keep counting."""
        if self.signal_at is None or now - self.signal_at > timedelta(
            seconds=ATTENTION_SIGNAL_MAX_AGE_SECONDS
        ):
            return None
        return self.signal


class Attention:
    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id
        self._students: dict[UUID, _Student] = {}

    def _student(self, user_id: UUID) -> _Student:
        return self._students.setdefault(user_id, _Student())

    # -- prompts --------------------------------------------------------------

    def issue(
        self, user_id: UUID, message: str, *, limit: int, ttl: timedelta, now: datetime
    ) -> Prompt | None:
        """A new prompt for the student, now waiting on them. None while an
        earlier one is still waiting, or once they have had limit of them."""
        student = self._student(user_id)
        if student.waiting is not None or student.sent >= limit:
            return None
        student.sent += 1
        student.unanswered += 1
        student.missed = 0
        student.waiting = Prompt(
            session_id=self.session_id,
            user_id=user_id,
            sent_at=now,
            payload=AttentionPromptPayload(
                prompt_id=uuid4(),
                message=message,
                expires_at=now + ttl,
                escalation=student.unanswered,
            ),
        )
        return student.waiting

    def waiting(self, user_id: UUID, now: datetime) -> Prompt | None:
        """The prompt still on this student's screen, if there is one."""
        student = self._students.get(user_id)
        prompt = student.waiting if student else None
        if prompt is None or now >= prompt.payload.expires_at:
            return None
        return prompt

    def pending(self) -> list[Prompt]:
        """Every prompt still waiting, whether or not its time is up."""
        return [s.waiting for s in self._students.values() if s.waiting is not None]

    def answer(
        self, user_id: UUID, prompt_id: UUID, *, dismissed: bool, now: datetime
    ) -> Prompt | None:
        """Take down the prompt the student answered. None when that prompt is
        not waiting on this student: unknown, someone else's, already answered
        or expired. Dismissing it does not reset the escalation."""
        prompt = self.waiting(user_id, now)
        if prompt is None or prompt.payload.prompt_id != prompt_id:
            return None
        student = self._students[user_id]
        student.waiting = None
        if not dismissed:
            student.unanswered = 0
        student.prompt_responses.append(PROMPT_DISMISSED if dismissed else PROMPT_ACKNOWLEDGED)
        return prompt

    def expire(self, prompt: Prompt) -> bool:
        """Take down a prompt whose time is up. False when it had already been
        answered or taken down."""
        student = self._students.get(prompt.user_id)
        if student is None or student.waiting is not prompt:
            return False
        student.waiting = None
        student.prompt_responses.append(PROMPT_EXPIRED)
        return True

    def withdraw_all(self) -> list[Prompt]:
        """Take down every prompt still waiting, as the session ends. Not
        counted as a response: the class ended, the student did not ignore it."""
        withdrawn = self.pending()
        for student in self._students.values():
            student.waiting = None
        return withdrawn

    def count_missed(
        self, shown: Set[UUID], answered: Set[UUID], threshold: int
    ) -> dict[UUID, int]:
        """Count a closed question towards each student's run of questions
        let pass. Returns the students whose run has reached threshold, with
        its length; a threshold of 0 returns nobody."""
        for user_id in answered:
            self._student(user_id).missed = 0
        due = {}
        for user_id in shown - answered:
            student = self._student(user_id)
            student.missed += 1
            if threshold and student.missed >= threshold:
                due[user_id] = student.missed
        return due

    # -- engagement -------------------------------------------------------------

    def observe(self, user_id: UUID, signal: AttentionSignalPayload, now: datetime) -> None:
        """Keep the student's latest attention signal for their next score."""
        student = self._student(user_id)
        student.signal = signal
        student.signal_at = now

    def score(
        self,
        shown: Set[UUID],
        answered: Set[UUID],
        timing: Mapping[UUID, float],
        now: datetime,
    ) -> list[ScoredStudent]:
        """Count a closed question towards everyone who was shown it, and
        rescore them. timing is the share of the window that had passed when
        each answer arrived."""
        scored = []
        for user_id in shown | answered:
            student = self._student(user_id)
            student.shown += 1
            if user_id in answered:
                student.answered += 1
                if user_id in timing:
                    student.response_times.append(timing[user_id])
            engagement = compute_engagement(
                EngagementInputs(
                    questions_shown=student.shown,
                    questions_answered=student.answered,
                    response_times=tuple(student.response_times),
                    prompt_responses=tuple(student.prompt_responses),
                    attention=student.current_signal(now),
                )
            )
            student.score = ScoredStudent(user_id, engagement, now)
            scored.append(student.score)
        return scored

    def scores(self) -> list[ScoredStudent]:
        """The latest score of every student scored so far."""
        return [s.score for s in self._students.values() if s.score is not None]
