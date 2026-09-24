"""The attention prompts of one live session, as bookkeeping.

Owner: General CS, Phase 3.

Which prompt is waiting on each student, how many each has been sent, how far
each has escalated and how many questions in a row each has let pass. The
classroom decides whether now is a fair time to prompt, sends the prompt,
runs its expiry timer and records its outcome, all under the session's lock;
this only keeps the counts and applies the per-student rules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.realtime.recorders import PromptOutcome, PromptResult
from app.schemas.events import AttentionPromptPayload

MAX_PROMPT_MESSAGE_LENGTH = 280


def checked_message(message: str) -> str:
    """The message a prompt carries, trimmed. A blank or overlong one is a
    programming error in whoever asked for the prompt."""
    message = message.strip()
    if not message or len(message) > MAX_PROMPT_MESSAGE_LENGTH:
        raise ValueError(f"A prompt message must be 1 to {MAX_PROMPT_MESSAGE_LENGTH} characters")
    return message


@dataclass
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


@dataclass
class _Student:
    sent: int = 0
    # Prompts in a row the student has not answered with "I'm here". This is
    # the escalation the next prompt carries, less one.
    unanswered: int = 0
    # Questions in a row the student was shown and did not answer.
    missed: int = 0
    waiting: Prompt | None = None


class Attention:
    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id
        self._students: dict[UUID, _Student] = {}

    def _student(self, user_id: UUID) -> _Student:
        return self._students.setdefault(user_id, _Student())

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
        return prompt

    def expire(self, prompt: Prompt) -> bool:
        """Take down a prompt whose time is up. False when it had already
        been answered or taken down."""
        student = self._students.get(prompt.user_id)
        if student is None or student.waiting is not prompt:
            return False
        student.waiting = None
        return True

    def withdraw_all(self) -> list[Prompt]:
        """Take down every prompt still waiting, and return them."""
        withdrawn = []
        for student in self._students.values():
            if student.waiting is not None:
                withdrawn.append(student.waiting)
                student.waiting = None
        return withdrawn

    def count_close(self, shown: Set[UUID], answered: Set[UUID], threshold: int) -> dict[UUID, int]:
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
