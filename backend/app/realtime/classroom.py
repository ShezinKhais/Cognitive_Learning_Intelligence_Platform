"""What a running session is doing from one second to the next.

Owner: General CS, Phase 3.

The database records what a session is (prepared, active or ended, and
whether it is paused) and which questions it has delivered. Which question is
open now, who has answered it, when its window shuts, when the next one is due
and which attention prompts are waiting on a student live here, in the
process that holds the session's sockets, and nowhere else.

The question cycle: once a question closes, the next is due after a fresh
random wait between checkpoint_interval_min_seconds and
checkpoint_interval_max_seconds, so the class cannot predict it. The wait
starts at the close, not the delivery, so the response window is never taken
out of the teaching time. A lecturer's manual question discards whatever was
due, and the next wait starts when that one closes.

One process runs a session. The state here is per process, so two backend
workers would each restore the same session and each run its cycle. Run the
backend with a single worker; check_wiring() refuses to start otherwise.

A restart loses the state. The question that was open is abandoned without a
question.closed, since its window has no owner any more. For persistence,
that delivery is over once its closes_at has passed: treat a delivery with no
recorded close and a closes_at in the past as closed by a restart, with its
respondents unknown. The cycle resumes the next time anything touches the
session: the lecturer's panel reconnecting, a student joining, or a manual
delivery. See restore(). A session paused in the database stays paused.

Scoring and storing answers, question closes and prompt outcomes belong to
AI 1 and BBIS. They plug in through ResponseRecorder, CloseRecorder and
PromptRecorder; until one is set, an accepted answer is counted towards the
question's respondents and kept nowhere else. check_wiring() says so at
startup, and refuses to start in production. Feedback on an answer is what
the ResponseRecorder returns, sent here after the receipt, and the answer
can be revealed from the CloseRecorder once the window is over.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.errors import ConflictError
from app.models.session import Session
from app.realtime.hub import SessionHub, hub
from app.repositories.session_repository import SessionRepository
from app.schemas.content import QuestionType
from app.schemas.events import (
    AlertKind,
    AlertRaisedPayload,
    AnswerReceiptPayload,
    AnswerSubmitPayload,
    AttentionPromptPayload,
    AttentionSignalPayload,
    FeedbackResultPayload,
    PromptAckPayload,
    QuestionClosedPayload,
    QuestionCloseReason,
    QuestionDeliveredPayload,
    ServerEventType,
    SessionStatePayload,
)
from app.schemas.identity import Role
from app.schemas.session import ClassComprehensionAlert, SessionStatus
from app.services.engagement import (
    ATTENTION_SIGNAL_MAX_AGE_SECONDS,
    PROMPT_ACKNOWLEDGED,
    PROMPT_DISMISSED,
    PROMPT_EXPIRED,
    EngagementComputation,
    EngagementInputs,
    compute_engagement,
    evaluate_comprehension_alert,
    should_send_dynamic_prompt,
)

_MCQ = QuestionType.MCQ.value

log = logging.getLogger("clip.classroom")

# A recorder that stops answering must not leave a student with no receipt,
# or an ended session waiting on a prompt outcome.
RECORD_TIMEOUT_SECONDS = 5.0

# Sessions this process has ended, remembered so a socket admitted a moment
# before the end cannot bring the session back to life or be told it is still
# waiting to start. Bounded because a process runs for weeks.
MAX_FINISHED_SESSIONS = 1024

MAX_PROMPT_MESSAGE_LENGTH = 280

# uvicorn and gunicorn read their worker count from this.
WORKERS_ENV = "WEB_CONCURRENCY"


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


@dataclass(frozen=True)
class QuestionComprehension:
    """The comprehension labels AI 1 has recorded for one delivered question."""

    labels: list[str]
    topic: str | None


class ComprehensionSource(Protocol):
    """Reads the classifications behind a class comprehension alert."""

    async def question_labels(
        self, session_id: UUID, question_id: UUID
    ) -> QuestionComprehension: ...


@dataclass
class _OpenQuestion:
    question_id: UUID
    option_count: int | None
    closes_at: datetime
    delivered: dict
    # Students who were shown the question: connected when it went out, or
    # given it on joining. Anyone who answers counts as eligible too.
    present: set[UUID]
    answered: set[UUID] = field(default_factory=set)
    closer: asyncio.Task[None] | None = None
    opened_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Per accepted answer, the share of the window that had passed when the
    # server received it. Server time, since client_elapsed_ms is the
    # client's own claim.
    timing: dict[UUID, float] = field(default_factory=dict)


@dataclass
class _Prompt:
    prompt_id: UUID
    escalation: int
    sent_at: datetime
    expires_at: datetime
    payload: dict
    expiry: asyncio.Task[None] | None = None


@dataclass
class _Attention:
    """One student's attention prompts in this session."""

    sent: int = 0
    # Prompts in a row the student has not answered with "I'm here". This is
    # the escalation the next prompt carries, less one.
    unanswered: int = 0
    # Questions in a row the student was shown and did not answer.
    missed: int = 0
    waiting: _Prompt | None = None
    # Engagement evidence for the whole session, fed to Cyber 1's scoring.
    shown: int = 0
    answered: int = 0
    response_times: list[float] = field(default_factory=list)
    prompt_responses: list[float] = field(default_factory=list)
    signal: AttentionSignalPayload | None = None
    signal_at: datetime | None = None
    engagement: EngagementComputation | None = None
    scored_at: datetime | None = None


@dataclass(frozen=True)
class ScoredStudent:
    user_id: UUID
    engagement: EngagementComputation
    scored_at: datetime


def _current_signal(attention: _Attention, now: datetime) -> AttentionSignalPayload | None:
    """The student's attention signal, unless it is too old to describe them
    now: a camera closed early in the lecture must not keep counting."""
    if attention.signal is None or attention.signal_at is None:
        return None
    if now - attention.signal_at > timedelta(seconds=ATTENTION_SIGNAL_MAX_AGE_SECONDS):
        return None
    return attention.signal


class LiveSession:
    def __init__(
        self,
        session_id: UUID,
        delivered: int,
        first_wait: timedelta | None,
        paused: bool = False,
    ) -> None:
        self.session_id = session_id
        # Every change to the open question, the pause and the prompts
        # happens under this lock, and so do the events announcing them, so
        # question.closed can never overtake the question.delivered it closes.
        self.lock = asyncio.Lock()
        self.open: _OpenQuestion | None = None
        self.delivered = delivered
        # When the cycle delivers next. None while a question is open, since
        # the next wait only starts once it closes, and when the cycle is off.
        self.next_due: datetime | None = None
        # What was left of the wait for the next question when it paused.
        self.remaining: timedelta | None = None
        if first_wait is not None:
            if paused:
                self.remaining = first_wait
            else:
                self.next_due = datetime.now(UTC) + first_wait
        # Set whenever next_due changes, so the cycle measures again.
        self.wake = asyncio.Event()
        self.cycle: asyncio.Task[None] | None = None
        self.paused = paused
        self.attention: dict[UUID, _Attention] = {}
        self.alerts: list[ClassComprehensionAlert] = []


class Classroom:
    """Every live session this process is running. One instance per process,
    for the same reason there is one hub."""

    def __init__(
        self,
        events: SessionHub = hub,
        sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory,
        settings: Callable[[], Settings] = get_settings,
        rng: random.Random | None = None,
    ) -> None:
        self._hub = events
        self._random = rng or random.Random()
        self._sessions = sessions
        self._settings = settings
        self._live: dict[UUID, LiveSession] = {}
        self._finished: OrderedDict[UUID, SessionStatus] = OrderedDict()
        self.recorder: ResponseRecorder | None = None
        self.prompt_recorder: PromptRecorder | None = None
        self.close_recorder: CloseRecorder | None = None
        self.comprehension_source: ComprehensionSource | None = None

    def _next_wait(self) -> timedelta | None:
        """A fresh random wait before the next scheduled question, or None
        when the cycle is off and the lecturer sends every question."""
        settings = self._settings()
        low = settings.checkpoint_interval_min_seconds
        high = settings.checkpoint_interval_max_seconds
        if high <= 0:
            return None
        return timedelta(seconds=self._random.uniform(low, high))

    def _set_due(self, live: LiveSession, wait: timedelta | None) -> None:
        """Schedule the next question after wait, or not at all for None."""
        live.next_due = None if wait is None else datetime.now(UTC) + wait
        live.wake.set()

    def check_wiring(self) -> None:
        """Say what a live session will not do in this deployment, at startup.

        Answers and prompt outcomes are kept nowhere until AI 1 and BBIS
        register their recorders, and a second worker would run a second
        cycle for every session. Development is told; production refuses to
        start rather than run a class that loses its answers.
        """
        problems = []
        if self.recorder is None:
            problems.append("no ResponseRecorder is registered, so answers are not stored")
        if self.prompt_recorder is None:
            problems.append("no PromptRecorder is registered, so prompt outcomes are not stored")
        if self.close_recorder is None:
            problems.append("no CloseRecorder is registered, so question closes are not stored")
        workers = os.environ.get(WORKERS_ENV, "1").strip() or "1"
        if not workers.isdigit() or int(workers) > 1:
            problems.append(
                f"{WORKERS_ENV}={workers}: live sessions need a single worker, or each "
                "worker runs its own question cycle for the same session"
            )
        if not problems:
            return
        if self._settings().is_production:
            raise RuntimeError("Refusing to start live sessions: " + "; ".join(problems))
        for problem in problems:
            log.warning("live sessions: %s", problem)

    @property
    def _window(self) -> timedelta:
        return timedelta(seconds=self._settings().checkpoint_response_window_seconds)

    # -- lifecycle ----------------------------------------------------------

    def get_running(self, session_id: UUID) -> LiveSession | None:
        return self._live.get(session_id)

    def activate(self, session_id: UUID, delivered: int = 0, paused: bool = False) -> LiveSession:
        """Begin running a session: its cycle starts counting from now."""
        live = self._live.get(session_id)
        if live is None:
            live = self._live[session_id] = LiveSession(
                session_id, delivered, self._next_wait(), paused
            )
            if not paused:
                self._start_cycle(live)
        return live

    async def restore(self, db: AsyncSession, row: Session) -> LiveSession | None:
        """The running state of an active session, rebuilt after a restart.

        None for a session that is not active, or that this process has
        already ended even if the row was read before the end.
        """
        if row.status != SessionStatus.ACTIVE.value or row.session_id in self._finished:
            return None
        live = self._live.get(row.session_id)
        if live is None:
            delivered = await SessionRepository(db).count_delivered(row.session_id)
            if row.session_id in self._finished:
                return None
            live = self.activate(row.session_id, delivered, paused=row.paused_at is not None)
        return live

    async def pause(self, db: AsyncSession, row: Session) -> None:
        """Record and apply a pause. The caller holds the row locked and has
        checked the session is active and running.

        No question goes out until it resumes, and no attention prompt. A
        question already open runs to the end of its window, so nobody loses
        an answer they were typing. The time left before the next scheduled
        question is kept for the resume.
        """
        live = await self.restore(db, row)
        if live is None:
            raise ConflictError("The session is not running.", {"status": row.status})
        # The change is recorded and applied under the session's lock, so a
        # pause and a resume sent together are applied in the order the
        # database took them.
        async with live.lock:
            row.paused_at = datetime.now(UTC)
            await db.commit()
            live.paused = True
            # None while a question is open: its close draws the next wait.
            live.remaining = (
                max(live.next_due - datetime.now(UTC), timedelta(0))
                if live.next_due is not None
                else None
            )
            live.next_due = None
            _cancel(live.cycle)
            live.cycle = None
            await self._announce(live.session_id, SessionStatus.ACTIVE)

    async def resume(self, db: AsyncSession, row: Session) -> None:
        """Record and apply the end of a pause. The next scheduled question
        comes after whatever was left of the wait when it paused."""
        live = await self.restore(db, row)
        if live is None:
            raise ConflictError("The session is not running.", {"status": row.status})
        async with live.lock:
            row.paused_at = None
            await db.commit()
            if live.paused:
                live.paused = False
                if live.open is None:
                    self._set_due(
                        live,
                        live.remaining if live.remaining is not None else self._next_wait(),
                    )
                live.remaining = None
                self._start_cycle(live)
            await self._announce(live.session_id, SessionStatus.ACTIVE)

    async def end(self, session_id: UUID, status: SessionStatus, delivered: int) -> None:
        """Close the open question, stop the cycle and tell everyone.

        The caller has already recorded the new status. Ending a session this
        process was not running, after a restart, still announces it. A
        prompt still waiting on a student is recorded as expired.
        """
        self._finished[session_id] = status
        self._finished.move_to_end(session_id)
        while len(self._finished) > MAX_FINISHED_SESSIONS:
            self._finished.popitem(last=False)

        live = self._live.pop(session_id, None)
        unanswered: list[PromptOutcome] = []
        closed = None
        if live is not None:
            async with live.lock:
                open_ = live.open
                closed = await self._close_locked(live, QuestionCloseReason.SESSION_ENDED)
                unanswered = self._drop_prompts_locked(live)
                # The last question still counts, but nobody is nudged in a
                # class that has ended.
                if open_ is not None:
                    self._score_locked(live, open_)
            _cancel(live.cycle)
        await self._announce(session_id, status, delivered)
        if live is not None and closed is not None:
            # Before the session is forgotten, so the lecturer can still be told.
            await self._check_comprehension(live, closed)
        self._hub.forget_session(session_id)
        await self._record_close(closed)
        for outcome in unanswered:
            await self._record_prompt(outcome)

    async def shutdown(self) -> None:
        """Stop every timer this process owns. Sessions stay active in the
        database and resume in whichever process next touches them."""
        tasks = []
        for live in self._live.values():
            tasks.append(live.cycle)
            if live.open is not None:
                tasks.append(live.open.closer)
            tasks.extend(a.waiting.expiry for a in live.attention.values() if a.waiting)
        self._live.clear()
        for task in tasks:
            _cancel(task)
        for task in tasks:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    def _start_cycle(self, live: LiveSession) -> None:
        # With the interval at 0 the lecturer sends every question.
        if self._settings().checkpoint_interval_max_seconds > 0:
            live.cycle = asyncio.create_task(
                self._run_cycle(live), name=f"question-cycle-{live.session_id}"
            )

    # -- what a client sees -------------------------------------------------

    def state(
        self, session_id: UUID, status: SessionStatus, delivered: int = 0
    ) -> SessionStatePayload:
        live = self._live.get(session_id)
        return SessionStatePayload(
            session_id=session_id,
            status=status,
            participant_count=len(self._hub.student_ids(session_id)),
            active_question_id=live.open.question_id if live and live.open else None,
            questions_delivered=live.delivered if live else delivered,
            paused=bool(live and live.paused),
        )

    async def announce(self, session_id: UUID, status: SessionStatus) -> None:
        """Tell the session its current state, as after a start."""
        await self._announce(session_id, status)

    async def announce_presence(
        self,
        session_id: UUID,
        recorded: SessionStatus,
    ) -> None:
        """Tell connected staff when the unique student count changes."""
        if session_id in self._live:
            status = SessionStatus.ACTIVE
        elif session_id in self._finished:
            return
        else:
            status = recorded

        payload = self.state(session_id, status).model_dump(mode="json")

        for staff_id in self._hub.staff_ids(session_id):
            await self._hub.send_to_user(
                session_id,
                staff_id,
                ServerEventType.SESSION_STATE,
                payload,
            )

    async def _announce(self, session_id: UUID, status: SessionStatus, delivered: int = 0) -> None:
        await self._hub.broadcast(
            session_id,
            ServerEventType.SESSION_STATE,
            self.state(session_id, status, delivered).model_dump(mode="json"),
        )

    def welcome(
        self, session_id: UUID, recorded: SessionStatus, user_id: UUID, role: Role | None
    ) -> list[tuple[ServerEventType, dict]]:
        """What a joining connection is told: the session's state, the
        question that is open unless this student has answered it, and any
        attention prompt still waiting on this student.

        recorded is the status read when the socket was admitted. The session
        may have started or ended since, and the event announcing it went out
        before this connection joined, so what this process knows now wins.

        A client reconnecting mid-question may also receive that question in
        the replay. Clients treat a second question.delivered with the same
        question_id as the same question.
        """
        if session_id in self._live:
            status = SessionStatus.ACTIVE
        elif session_id in self._finished:
            status = self._finished[session_id]
        elif recorded is SessionStatus.ACTIVE:
            status = SessionStatus.ENDED
        else:
            status = recorded
        state = self.state(session_id, status).model_dump(mode="json")
        events = [(ServerEventType.SESSION_STATE, state)]
        live = self._live.get(session_id)
        if live is None:
            return events

        now = datetime.now(UTC)
        open_ = live.open
        if open_ is not None and now < open_.closes_at:
            if role is not Role.STUDENT:
                # The lecturer's panel shows the question and its timer.
                events.append((ServerEventType.QUESTION_DELIVERED, open_.delivered))
            elif user_id not in open_.answered:
                # Shown the question, so expected to answer it.
                open_.present.add(user_id)
                events.append((ServerEventType.QUESTION_DELIVERED, open_.delivered))

        attention = live.attention.get(user_id)
        if attention and attention.waiting and now < attention.waiting.expires_at:
            events.append((ServerEventType.PROMPT_ATTENTION, attention.waiting.payload))
        return events

    # -- delivery -----------------------------------------------------------

    async def deliver(
        self, db: AsyncSession, row: Session, question_id: UUID | None = None
    ) -> QuestionDeliveredPayload | None:
        """Deliver the named question, or the next staged one, to the session.

        The lecturer's manual trigger and the cycle both come through here.
        The caller holds the session row locked and has checked it is active.
        Returns None when there is nothing staged to deliver. Raises
        ConflictError while the session is paused or another question is
        still open.
        """
        live = await self.restore(db, row)
        if live is None:
            raise ConflictError("The session is not running.", {"status": row.status})

        async with live.lock:
            if live.paused:
                raise ConflictError(
                    "The session is paused. Resume it to deliver a question.",
                    {"session_id": str(row.session_id)},
                )
            if live.open is not None:
                raise ConflictError(
                    "A question is already open.",
                    {"question_id": str(live.open.question_id)},
                )
            question = await SessionRepository(db).claim_for_delivery(row, question_id)
            if question is None:
                return None
            now = datetime.now(UTC)
            window = self._window
            # question_type decides how it is answered, not whether options
            # happen to be set. Reading it from the options alone turned a
            # multiple choice question whose choices were missing into a
            # free-text one, and the student was told to answer in their own
            # words while their screen offered buttons. The repository will
            # not hand out such a question, and this agrees with it.
            choices = question.options if question.question_type == _MCQ else None
            payload = QuestionDeliveredPayload(
                question_id=question.question_id,
                prompt=question.question_text,
                options=choices,
                closes_at=now + window,
                window_seconds=int(window.total_seconds()),
                source_slide=question.source_slide,
            )
            # Recorded before anyone is told, so a delivered question is
            # never missing from the session's history.
            await db.commit()

            live.open = _OpenQuestion(
                question_id=question.question_id,
                option_count=len(choices) if choices else None,
                closes_at=payload.closes_at,
                delivered=payload.model_dump(mode="json"),
                present=self._hub.student_ids(row.session_id),
                opened_at=now,
            )
            live.delivered += 1
            # Whatever was due is discarded, manual or scheduled: the next
            # wait is drawn when this question closes, so the cycle never
            # sends another moments after the lecturer did.
            live.next_due = None
            await self._hub.broadcast(
                row.session_id, ServerEventType.QUESTION_DELIVERED, live.open.delivered
            )
            live.open.closer = asyncio.create_task(
                self._close_when_due(live, live.open),
                name=f"response-window-{question.question_id}",
            )
        return payload

    async def _close_when_due(self, live: LiveSession, open_: _OpenQuestion) -> None:
        delay = (open_.closes_at - datetime.now(UTC)).total_seconds()
        await asyncio.sleep(max(delay, 0.0))
        closed = None
        async with live.lock:
            if live.open is open_:
                closed = await self._close_locked(live, QuestionCloseReason.WINDOW_ELAPSED)
                await self._nudge_absent_locked(live, open_)
                await self._score_engagement_locked(live, open_)
        await self._record_close(closed)
        if closed is not None:
            await self._check_comprehension(live, closed)

    async def _close_locked(
        self, live: LiveSession, reason: QuestionCloseReason
    ) -> ClosedQuestion | None:
        """Close the open question and say so. Returns what the close
        recorder is to be given once the caller releases the lock."""
        open_ = live.open
        if open_ is None:
            return None
        live.open = None
        if open_.closer is not asyncio.current_task():
            _cancel(open_.closer)
        payload = QuestionClosedPayload(
            question_id=open_.question_id,
            reason=reason,
            respondents=len(open_.answered),
            eligible=len(open_.present | open_.answered),
        )
        await self._hub.broadcast(
            live.session_id, ServerEventType.QUESTION_CLOSED, payload.model_dump(mode="json")
        )
        closed = ClosedQuestion(
            session_id=live.session_id,
            question_id=open_.question_id,
            reason=reason,
            closed_at=datetime.now(UTC),
            eligible=frozenset(open_.present | open_.answered),
            answered=frozenset(open_.answered),
        )
        if reason is QuestionCloseReason.SESSION_ENDED:
            return closed
        # The next wait starts now, not at the delivery, so the response
        # window is not taken out of the teaching time.
        wait = self._next_wait()
        if live.paused:
            live.remaining = wait
        else:
            self._set_due(live, wait)
        return closed

    async def _run_cycle(self, live: LiveSession) -> None:
        """Deliver the next staged question whenever one falls due."""
        while True:
            due = live.next_due
            if due is None:
                # A question is open; its close sets the next due time.
                live.wake.clear()
                await live.wake.wait()
                continue
            wait = (due - datetime.now(UTC)).total_seconds()
            if wait > 0:
                # Woken early when next_due changes; the loop measures again.
                live.wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(live.wake.wait(), wait)
                continue
            live.next_due = None
            try:
                if not await self._deliver_on_schedule(live):
                    # Ended by a call that found nothing running here, such as
                    # an end racing a start. Nothing else will remove it.
                    if self._live.get(live.session_id) is live:
                        del self._live[live.session_id]
                    return
            except ConflictError:
                pass  # Paused, or a manual question is open; its close reschedules.
            except Exception:
                log.exception("scheduled delivery failed for session %s", live.session_id)
                self._set_due(live, self._next_wait())

    async def _deliver_on_schedule(self, live: LiveSession) -> bool:
        """One scheduled delivery. False once the session is no longer active.

        The row stays locked until deliver() commits, so an end arriving
        meanwhile waits for the delivery and then closes the question.

        With nothing staged the lecturer is not interrupted: it is logged and
        the cycle tries again after a fresh wait.
        """
        async with self._sessions()() as db:
            row = await SessionRepository(db).get(live.session_id, for_update=True)
            if row is None or row.status != SessionStatus.ACTIVE.value:
                return False
            delivered = await self.deliver(db, row)
        if delivered is None:
            log.info("No static question available for session %s", live.session_id)
            if live.open is None and live.next_due is None:
                self._set_due(live, self._next_wait())
        return True

    # -- answers ------------------------------------------------------------

    async def submit(
        self,
        session_id: UUID,
        user_id: UUID,
        role: Role | None,
        answer: AnswerSubmitPayload,
    ) -> AnswerReceiptPayload:
        """Accept or refuse one answer and tell the student.

        Every outcome is a receipt, never an exception, so the student always
        hears back. It goes to every tab they have open, so none of them
        offers the question again. The recorder's feedback follows the
        receipt, and only for an accepted answer: a student is never shown a
        result for an answer that was then refused.
        """
        receipt, feedback = await self._accept(session_id, user_id, role, answer)
        await self._hub.send_to_user(
            session_id, user_id, ServerEventType.ANSWER_RECEIPT, receipt.model_dump(mode="json")
        )
        if feedback is not None:
            await self._hub.send_to_user(
                session_id,
                user_id,
                ServerEventType.FEEDBACK_RESULT,
                feedback.model_dump(mode="json"),
            )
        return receipt

    async def _accept(
        self,
        session_id: UUID,
        user_id: UUID,
        role: Role | None,
        answer: AnswerSubmitPayload,
    ) -> tuple[AnswerReceiptPayload, FeedbackResultPayload | None]:
        received_at = datetime.now(UTC)

        def refused(reason: str) -> tuple[AnswerReceiptPayload, None]:
            receipt = AnswerReceiptPayload(
                question_id=answer.question_id,
                accepted=False,
                received_at=received_at,
                reason=reason,
            )
            return receipt, None

        if role is not Role.STUDENT:
            return refused("Only students answer questions.")
        live = self._live.get(session_id)
        if live is None:
            return refused("This question is not open.")

        async with live.lock:
            open_ = live.open
            if open_ is None or open_.question_id != answer.question_id:
                return refused("This question is not open.")
            if received_at >= open_.closes_at:
                return refused("The response window has closed.")
            if user_id in open_.answered:
                return refused("You have already answered this question.")
            if open_.option_count is not None:
                if answer.selected_option is None:
                    return refused("Choose one of the options.")
                if answer.selected_option >= open_.option_count:
                    return refused("That option is not one of the choices.")
            elif answer.free_text is None:
                return refused("Answer this question in your own words.")
            open_.answered.add(user_id)
            window = (open_.closes_at - open_.opened_at).total_seconds()
            if window > 0:
                open_.timing[user_id] = (received_at - open_.opened_at).total_seconds() / window

        feedback = None
        if self.recorder is not None:
            try:
                async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
                    feedback = await self.recorder.record(
                        Submission(
                            session_id=session_id,
                            question_id=answer.question_id,
                            user_id=user_id,
                            selected_option=answer.selected_option,
                            free_text=answer.free_text,
                            client_elapsed_ms=answer.client_elapsed_ms,
                            received_at=received_at,
                        )
                    )
            except Exception:
                log.exception("could not record an answer in session %s", session_id)
                async with live.lock:
                    open_.answered.discard(user_id)
                    open_.timing.pop(user_id, None)
                    still_open = live.open is open_ and datetime.now(UTC) < open_.closes_at
                if still_open:
                    return refused("Your answer could not be saved. Please submit it again.")
                return refused("Your answer could not be saved.")

        receipt = AnswerReceiptPayload(
            question_id=answer.question_id, accepted=True, received_at=received_at
        )
        return receipt, feedback

    # -- attention prompts --------------------------------------------------

    async def prompt_student(
        self, session_id: UUID, user_id: UUID, message: str
    ) -> AttentionPromptPayload | None:
        """Send one student a private attention prompt, if now is a fair time.

        Engagement scoring (Cyber 1) decides who needs one; this decides
        whether it goes out. It does not while the session is paused, while
        the student has a question to answer, while an earlier prompt is
        still waiting on them, once they have had
        dynamic_prompt_max_per_student this session, or when they are not
        connected. Returns what was sent, or None.

        escalation counts the prompts in a row the student has not answered
        with "I'm here". Dismissing a prompt does not reset it.
        """
        message = message.strip()
        if not message or len(message) > MAX_PROMPT_MESSAGE_LENGTH:
            raise ValueError(
                f"A prompt message must be 1 to {MAX_PROMPT_MESSAGE_LENGTH} characters"
            )
        live = self._live.get(session_id)
        if live is None:
            return None
        async with live.lock:
            return await self._prompt_locked(live, user_id, message)

    async def _prompt_locked(
        self, live: LiveSession, user_id: UUID, message: str
    ) -> AttentionPromptPayload | None:
        settings = self._settings()
        if live.paused or user_id not in self._hub.student_ids(live.session_id):
            return None
        if live.open is not None and user_id not in live.open.answered:
            return None
        attention = live.attention.setdefault(user_id, _Attention())
        if attention.waiting is not None:
            return None
        if attention.sent >= settings.dynamic_prompt_max_per_student:
            return None

        now = datetime.now(UTC)
        attention.sent += 1
        attention.unanswered += 1
        attention.missed = 0
        payload = AttentionPromptPayload(
            prompt_id=uuid4(),
            message=message,
            expires_at=now + timedelta(seconds=settings.attention_prompt_ttl_seconds),
            escalation=attention.unanswered,
        )
        prompt = attention.waiting = _Prompt(
            prompt_id=payload.prompt_id,
            escalation=payload.escalation,
            sent_at=now,
            expires_at=payload.expires_at,
            payload=payload.model_dump(mode="json"),
        )
        prompt.expiry = asyncio.create_task(
            self._expire_when_due(live, user_id, prompt),
            name=f"attention-prompt-{prompt.prompt_id}",
        )
        await self._hub.send_to_user(
            live.session_id, user_id, ServerEventType.PROMPT_ATTENTION, prompt.payload
        )
        return payload

    async def _nudge_absent_locked(self, live: LiveSession, closed: _OpenQuestion) -> None:
        """Count the questions each student was shown and let pass, and nudge
        one who has missed attention_prompt_after_missed_questions in a row.

        This is the scheduler's own trigger, from what it already knows.
        Engagement scoring can prompt for its own reasons through
        prompt_student(); both obey the same limits.
        """
        threshold = self._settings().attention_prompt_after_missed_questions
        for user_id in closed.answered:
            live.attention.setdefault(user_id, _Attention()).missed = 0
        for user_id in closed.present - closed.answered:
            attention = live.attention.setdefault(user_id, _Attention())
            attention.missed += 1
            if threshold and attention.missed >= threshold:
                await self._prompt_locked(live, user_id, _missed_message(attention.missed))

    async def acknowledge_prompt(
        self, session_id: UUID, user_id: UUID, ack: PromptAckPayload
    ) -> bool:
        """A student's answer to their own prompt. False when that prompt is
        not waiting on this student: unknown, someone else's, already
        answered or expired."""
        live = self._live.get(session_id)
        if live is None:
            return False
        now = datetime.now(UTC)
        async with live.lock:
            attention = live.attention.get(user_id)
            prompt = attention.waiting if attention else None
            if prompt is None or prompt.prompt_id != ack.prompt_id or now >= prompt.expires_at:
                return False
            attention.waiting = None  # type: ignore[union-attr]
            _cancel(prompt.expiry)
            if not ack.dismissed:
                attention.unanswered = 0  # type: ignore[union-attr]
            attention.prompt_responses.append(  # type: ignore[union-attr]
                PROMPT_DISMISSED if ack.dismissed else PROMPT_ACKNOWLEDGED
            )
        result = PromptResult.DISMISSED if ack.dismissed else PromptResult.ACKNOWLEDGED
        await self._record_prompt(_outcome(session_id, user_id, prompt, result, now))
        return True

    async def _expire_when_due(self, live: LiveSession, user_id: UUID, prompt: _Prompt) -> None:
        delay = (prompt.expires_at - datetime.now(UTC)).total_seconds()
        await asyncio.sleep(max(delay, 0.0))
        async with live.lock:
            attention = live.attention.get(user_id)
            if attention is None or attention.waiting is not prompt:
                return
            attention.waiting = None
            attention.prompt_responses.append(PROMPT_EXPIRED)
        await self._record_prompt(
            _outcome(live.session_id, user_id, prompt, PromptResult.EXPIRED, None)
        )

    # -- engagement and comprehension (Cyber 1) --------------------------------

    async def record_attention(
        self, session_id: UUID, user_id: UUID, signal: AttentionSignalPayload
    ) -> bool:
        """Keep a student's latest client attention signal for their next
        engagement score. False when the session is not running here or the
        sender is not a student connected to it."""
        live = self._live.get(session_id)
        if live is None or user_id not in self._hub.student_ids(session_id):
            return False
        async with live.lock:
            attention = live.attention.setdefault(user_id, _Attention())
            attention.signal = signal
            attention.signal_at = datetime.now(UTC)
        return True

    async def _score_engagement_locked(self, live: LiveSession, closed: _OpenQuestion) -> None:
        """Rescore everyone who was shown the question that just closed, and
        nudge those engagement scoring says need it. prompt_student's limits
        (cap, pause, one at a time, connected) still apply."""
        for user_id in self._score_locked(live, closed):
            attention = live.attention[user_id]
            if attention.engagement is not None and should_send_dynamic_prompt(
                attention.engagement
            ):
                await self._prompt_locked(live, user_id, ENGAGEMENT_PROMPT_MESSAGE)

    def _score_locked(self, live: LiveSession, closed: _OpenQuestion) -> list[UUID]:
        """Count the closed question towards everyone who was shown it and
        rescore them. Returns who was scored."""
        now = datetime.now(UTC)
        scored = []
        for user_id in closed.present | closed.answered:
            attention = live.attention.setdefault(user_id, _Attention())
            attention.shown += 1
            if user_id in closed.answered:
                attention.answered += 1
                if user_id in closed.timing:
                    attention.response_times.append(closed.timing[user_id])
            attention.engagement = compute_engagement(
                EngagementInputs(
                    questions_shown=attention.shown,
                    questions_answered=attention.answered,
                    response_times=tuple(attention.response_times),
                    prompt_responses=tuple(attention.prompt_responses),
                    attention=_current_signal(attention, now),
                )
            )
            attention.scored_at = now
            scored.append(user_id)
        return scored

    async def _check_comprehension(self, live: LiveSession, closed: ClosedQuestion) -> None:
        """Raise a class comprehension alert to the lecturer once enough of
        the class has been classified partial or struggling on a question."""
        if self.comprehension_source is None:
            return
        settings = self._settings()
        try:
            async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
                found = await self.comprehension_source.question_labels(
                    closed.session_id, closed.question_id
                )
        except Exception:
            log.exception("could not read comprehension for session %s", closed.session_id)
            return
        decision = evaluate_comprehension_alert(
            found.labels,
            min_respondents=settings.comprehension_alert_min_respondents,
            threshold=settings.comprehension_alert_threshold,
        )
        if not decision.should_alert or decision.correct_ratio is None:
            return
        alert = ClassComprehensionAlert(
            session_id=closed.session_id,
            question_id=closed.question_id,
            topic=found.topic,
            correct_ratio=decision.correct_ratio,
            respondents=decision.respondents,
            threshold=settings.comprehension_alert_threshold,
            raised_at=datetime.now(UTC),
        )
        live.alerts.append(alert)
        about = f" on {found.topic}" if found.topic else ""
        payload = AlertRaisedPayload(
            alert_id=uuid4(),
            kind=AlertKind.TOPIC_DIFFICULTY,
            message=f"Much of the class is struggling{about}.",
            reason=(
                f"{round((decision.struggling_ratio or 0.0) * decision.respondents)} of "
                f"{decision.respondents} classified answers were partial or struggling."
            ),
            confidence=min(1.0, decision.respondents / max(len(closed.eligible), 1)),
        ).model_dump(mode="json")
        for staff_id in self._hub.staff_ids(closed.session_id):
            await self._hub.send_to_user(
                closed.session_id, staff_id, ServerEventType.ALERT_RAISED, payload
            )

    def engagement(self, session_id: UUID) -> list[ScoredStudent]:
        """The latest engagement score of each student scored in a session this
        process is running, by user id. The caller resolves the student id."""
        live = self._live.get(session_id)
        if live is None:
            return []
        return [
            ScoredStudent(user_id=user_id, engagement=a.engagement, scored_at=a.scored_at)
            for user_id, a in live.attention.items()
            if a.engagement is not None and a.scored_at is not None
        ]

    def alerts(self, session_id: UUID) -> list[ClassComprehensionAlert]:
        live = self._live.get(session_id)
        return list(live.alerts) if live is not None else []

    def _drop_prompts_locked(self, live: LiveSession) -> list[PromptOutcome]:
        outcomes = []
        for user_id, attention in live.attention.items():
            prompt = attention.waiting
            if prompt is None:
                continue
            attention.waiting = None
            _cancel(prompt.expiry)
            outcomes.append(_outcome(live.session_id, user_id, prompt, PromptResult.EXPIRED, None))
        return outcomes

    async def _record_prompt(self, outcome: PromptOutcome) -> None:
        if self.prompt_recorder is None:
            return
        try:
            async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
                await self.prompt_recorder.record_prompt(outcome)
        except Exception:
            log.exception("could not record a prompt outcome in session %s", outcome.session_id)

    async def _record_close(self, closed: ClosedQuestion | None) -> None:
        # Called once the session's lock is released, so a slow store never
        # holds up a pause, a delivery or the next answer.
        if closed is None or self.close_recorder is None:
            return
        try:
            async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
                await self.close_recorder.record_close(closed)
        except Exception:
            log.exception("could not record a question close in session %s", closed.session_id)


def _outcome(
    session_id: UUID,
    user_id: UUID,
    prompt: _Prompt,
    result: PromptResult,
    responded_at: datetime | None,
) -> PromptOutcome:
    return PromptOutcome(
        session_id=session_id,
        prompt_id=prompt.prompt_id,
        user_id=user_id,
        escalation=prompt.escalation,
        sent_at=prompt.sent_at,
        expires_at=prompt.expires_at,
        result=result,
        responded_at=responded_at,
    )


ENGAGEMENT_PROMPT_MESSAGE = "Quick check-in: are you still following along?"


def _missed_message(missed: int) -> str:
    return f"You have missed the last {missed} questions. Still with us?"


def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is not None and task is not asyncio.current_task():
        task.cancel()


classroom = Classroom()
