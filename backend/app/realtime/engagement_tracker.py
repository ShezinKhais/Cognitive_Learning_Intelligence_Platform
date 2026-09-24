"""The engagement evidence of one live session, as bookkeeping.

Owner: Cyber 1, Phase 3, for the scoring; General CS for where it is kept.

For each student: how many questions they were shown and answered, how far
into each window they answered, how their attention prompts ended, and their
latest client attention signal. Each close rescores everyone who was shown
the question with app.services.engagement. The classroom decides when to
count a close and whether a score earns a prompt, under the session's lock.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.schemas.events import AttentionSignalPayload
from app.services.engagement import (
    ATTENTION_SIGNAL_MAX_AGE_SECONDS,
    EngagementComputation,
    EngagementInputs,
    compute_engagement,
)

ENGAGEMENT_PROMPT_MESSAGE = "Quick check-in: are you still following along?"


@dataclass(frozen=True)
class ScoredStudent:
    user_id: UUID
    engagement: EngagementComputation
    scored_at: datetime


@dataclass
class _Evidence:
    shown: int = 0
    answered: int = 0
    response_times: list[float] = field(default_factory=list)
    prompt_responses: list[float] = field(default_factory=list)
    signal: AttentionSignalPayload | None = None
    signal_at: datetime | None = None
    scored: ScoredStudent | None = None

    def current_signal(self, now: datetime) -> AttentionSignalPayload | None:
        """The attention signal, unless it is too old to describe the student
        now: a camera closed early in the lecture must not keep counting."""
        if self.signal is None or self.signal_at is None:
            return None
        if now - self.signal_at > timedelta(seconds=ATTENTION_SIGNAL_MAX_AGE_SECONDS):
            return None
        return self.signal


class EngagementTracker:
    def __init__(self) -> None:
        self._students: dict[UUID, _Evidence] = {}

    def _student(self, user_id: UUID) -> _Evidence:
        return self._students.setdefault(user_id, _Evidence())

    def signal(self, user_id: UUID, signal: AttentionSignalPayload, now: datetime) -> None:
        student = self._student(user_id)
        student.signal = signal
        student.signal_at = now

    def prompt_ended(self, user_id: UUID, response: float) -> None:
        """How a prompt ended, as one of app.services.engagement's PROMPT_*."""
        self._student(user_id).prompt_responses.append(response)

    def count_close(
        self,
        shown: Set[UUID],
        answered: Set[UUID],
        timing: Mapping[UUID, float],
        now: datetime,
    ) -> dict[UUID, EngagementComputation]:
        """Count a closed question towards everyone who was shown it or
        answered it, and rescore them. Returns the new scores."""
        scores = {}
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
            student.scored = ScoredStudent(user_id, engagement, now)
            scores[user_id] = engagement
        return scores

    def scores(self) -> list[ScoredStudent]:
        """The latest score of each student scored so far."""
        return [s.scored for s in self._students.values() if s.scored is not None]
