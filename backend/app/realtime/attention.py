"""What one live session knows about each student's attention.

Owner: General CS, Phase 3, with Cyber 1's engagement evidence.

Which attention prompt is waiting on each student, how many each has been
sent, how far each has escalated and how many questions in a row each has let
pass; and the evidence engagement scoring reads: questions shown and
answered, how quickly, how prompts were answered, and the recent signals from
the student's own device, as one rolling window (signals.py), with every
signal of the current minute gathered for storing (attention_windows.py).
The classroom decides whether now is a fair time to prompt, sends the prompt,
runs its expiry timer and records its outcome, all under the session's lock.
This keeps the counts and applies the per-student rules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.realtime.attention_windows import AttentionWindows
from app.realtime.recorders import AttentionWindow, PromptOutcome, PromptResult
from app.realtime.signals import SignalWindow
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
from app.services.engagement_baseline import PersonalBaseline

MAX_PROMPT_MESSAGE_LENGTH = 280

# The longest one summary may claim to cover in the rolling window. The client
# sends one every five seconds; a tab that was asleep may send a longer one.
MAX_SUMMARY_SECONDS = 30.0


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
    signals: SignalWindow = field(default_factory=SignalWindow)
    score: ScoredStudent | None = None
    # When a prompt was last sent on the strength of the signals alone.
    refocused_at: datetime | None = None
    # The student's own normal for this session, and the newest signal it
    # learned from, so one reading is never counted twice.
    baseline: PersonalBaseline = field(default_factory=PersonalBaseline)
    baseline_from: datetime | None = None

    def current_signal(self, now: datetime) -> AttentionSignalPayload | None:
        """The student's recent signals as one, leaving out any too old to
        describe them now: a camera closed early in the lecture must not keep
        counting."""
        return self.signals.summary(now, timedelta(seconds=ATTENTION_SIGNAL_MAX_AGE_SECONDS))

    def learn_baseline(self, now: datetime) -> None:
        """Teach the baseline the student's recent signals, once per new
        signal: a question closing with nothing new received adds nothing."""
        signal = self.current_signal(now)
        newest = self.signals.newest_at()
        if signal is not None and newest != self.baseline_from:
            self.baseline.record(signal.gaze_on_screen_ratio, signal.face_present)
            self.baseline_from = newest

    def engagement(self, now: datetime, accommodated: bool = False) -> EngagementComputation:
        return compute_engagement(
            EngagementInputs(
                questions_shown=self.shown,
                questions_answered=self.answered,
                response_times=tuple(self.response_times),
                prompt_responses=tuple(self.prompt_responses),
                attention=self.current_signal(now),
                baseline=self.baseline,
                accommodated=accommodated,
            )
        )


class Attention:
    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id
        self._students: dict[UUID, _Student] = {}
        self.windows = AttentionWindows(session_id)

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

    def observe(
        self, user_id: UUID, signal: AttentionSignalPayload, now: datetime
    ) -> tuple[AttentionSignalPayload | None, list[AttentionWindow]]:
        """Add an attention signal to the student's rolling window for their
        next score, and to their current minute. A signal sent too soon after
        their last one is dropped (see attention_windows.py). Returns the
        signal as kept, or None when it was dropped, and the minutes now over
        and ready to store."""
        kept, finished = self.windows.add(user_id, signal, now)
        if kept is not None:
            self._student(user_id).signals.add(kept, now, MAX_SUMMARY_SECONDS)
        return kept, finished

    def signal(self, user_id: UUID, now: datetime) -> AttentionSignalPayload | None:
        """The student's recent signals as one, or None with none recent."""
        student = self._students.get(user_id)
        return student.current_signal(now) if student is not None else None

    def observed(self) -> list[UUID]:
        """Every student a signal is held for, recent or not."""
        return [user_id for user_id, s in self._students.items() if len(s.signals)]

    def rescore(self, user_id: UUID, now: datetime, accommodated: bool = False) -> ScoredStudent:
        """Score the student again on what is known now, between questions.
        Nothing is counted and the baseline learns nothing: only the signals
        have changed, and the baseline learns once per question."""
        student = self._student(user_id)
        student.score = ScoredStudent(user_id, student.engagement(now, accommodated), now)
        return student.score

    def refocus_due(self, user_id: UUID, now: datetime, cooldown: timedelta) -> bool:
        """Whether long enough has passed since the signals last prompted
        this student. A student still looking away is not prompted every few
        seconds."""
        at = self._student(user_id).refocused_at
        return at is None or now - at >= cooldown

    def refocused(self, user_id: UUID, now: datetime) -> None:
        self._student(user_id).refocused_at = now

    def forget(self, user_id: UUID) -> Prompt | None:
        """Drop all engagement evidence and the score kept for a student whose
        consent to monitoring is withdrawn. Returns the prompt that was
        waiting on them, now taken down; it is not counted as a response,
        since the student did not ignore it. How many prompts they have been
        sent is kept, so the per-student cap still holds if they consent again.
        """
        self.windows.forget(user_id)
        student = self._students.pop(user_id, None)
        if student is None:
            return None
        self._students[user_id] = _Student(sent=student.sent, refocused_at=student.refocused_at)
        return student.waiting

    def restrict_signal(
        self,
        user_id: UUID,
        keep: Callable[[AttentionSignalPayload], AttentionSignalPayload | None],
    ) -> None:
        """Narrow the student's stored signals, and their unsent minute, to
        what keep allows, as when camera or microphone consent is withdrawn."""
        self.windows.restrict(user_id, keep)
        student = self._students.get(user_id)
        if student is not None:
            student.signals.restrict(keep)

    def score(
        self,
        shown: Set[UUID],
        answered: Set[UUID],
        timing: Mapping[UUID, float],
        now: datetime,
        accommodated: Set[UUID] = frozenset(),
    ) -> list[ScoredStudent]:
        """Count a closed question towards everyone who was shown it, and
        rescore them. timing is the share of the window that had passed when
        each answer arrived. accommodated is who has a recorded accommodation:
        their scoring leaves out the signals that assume one way of
        interacting (see engagement.py)."""
        scored = []
        for user_id in shown | answered:
            student = self._student(user_id)
            student.shown += 1
            if user_id in answered:
                student.answered += 1
                if user_id in timing:
                    student.response_times.append(timing[user_id])
            student.learn_baseline(now)
            student.score = ScoredStudent(
                user_id, student.engagement(now, user_id in accommodated), now
            )
            scored.append(student.score)
        return scored

    def scores(self) -> list[ScoredStudent]:
        """The latest score of every student scored so far."""
        return [s.score for s in self._students.values() if s.score is not None]

    def purge_visual(self, user_id: UUID) -> None:
        """Forget what was learned from the student's camera, as their camera
        consent is withdrawn. Their participation evidence stays."""
        student = self._students.get(user_id)
        if student is not None:
            student.baseline.purge_visual()
