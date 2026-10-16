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

What is stored, scored and alerted on plugs in through the contracts in
recorders.py. Feedback on an answer is what the ResponseRecorder returns,
sent here after the receipt, and the answer can be revealed from the
CloseRecorder once the window is over.

Phase 6 adds the watch: once a session has an attention signal or a breakout
room, a timer looks at both every signal_watch_seconds. It rescores the
students whose devices are reporting, sends a private prompt to one whose
signals have stayed low, and tells the lecturer how each room is doing. See
signals.py and rooms.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.errors import ConflictError
from app.models.session import Session
from app.realtime.accommodations import Accommodations
from app.realtime.attention import Attention, Prompt, ScoredStudent, checked_message
from app.realtime.consent import CLOSE_CONSENT, ConsentRegistry, permitted_signal
from app.realtime.countdown import Countdown
from app.realtime.hub import SessionHub, hub
from app.realtime.recorders import (
    RECORD_TIMEOUT_SECONDS,
    AlertRecorder,
    Attendance,
    AttentionRecorder,
    AttentionWindow,
    ClosedQuestion,
    CloseRecorder,
    ComprehensionSource,
    ParticipantRecorder,
    PromptOutcome,
    PromptRecorder,
    PromptResult,
    QuestionComprehension,
    ResponseRecorder,
    RoomAlert,
    Submission,
    best_effort,
)
from app.realtime.rooms import Refusal, RoomLimits, Rooms
from app.realtime.signals import signals_low
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
    RoomConfirmPayload,
    RoomStatusPayload,
    ServerEventType,
    SessionStatePayload,
)
from app.schemas.identity import ConsentType, Role
from app.schemas.session import ClassComprehensionAlert, SessionStatus
from app.services.ai_explainability import (
    AlertExplanation,
    TopicEvidence,
    explain_topic_difficulty,
    fallback_explanation,
)
from app.services.engagement import evaluate_comprehension_alert, should_send_dynamic_prompt

log = logging.getLogger("clip.classroom")

# Sessions this process has ended, remembered so a socket admitted a moment
# before the end cannot bring the session back to life or be told it is still
# waiting to start. Bounded because a process runs for weeks.
MAX_FINISHED_SESSIONS = 1024

# uvicorn and gunicorn read their worker count from this.
WORKERS_ENV = "WEB_CONCURRENCY"

ENGAGEMENT_PROMPT_MESSAGE = "Quick check-in: are you still following along?"
# Sent when a student's own device has reported them away for a while.
REFOCUS_PROMPT_MESSAGE = "Quick check-in: are you still with the class?"

NOT_OPEN = "This question is not open."


@dataclass(slots=True)
class _OpenQuestion:
    question: QuestionDeliveredPayload
    # Students who were shown the question: connected when it went out, or
    # given it on joining. Anyone who answers counts as eligible too.
    present: set[UUID]
    opened_at: datetime
    answered: set[UUID] = field(default_factory=set)
    # Per accepted answer, the share of the window that had passed when the
    # server received it. Server time, since client_elapsed_ms is the
    # client's own claim.
    timing: dict[UUID, float] = field(default_factory=dict)
    closer: asyncio.Task[None] | None = None
    # One per accepted answer, resolved once the recorder has stored it or
    # given up. The close waits on these, so everything it announces, scores
    # and stores counts only answers that were kept.
    saving: list[asyncio.Future[None]] = field(default_factory=list)

    @property
    def eligible(self) -> set[UUID]:
        return self.present | self.answered

    def refusal(self, user_id: UUID, answer: AnswerSubmitPayload, at: datetime) -> str | None:
        """Why this answer cannot be accepted, or None if it can."""
        if answer.question_id != self.question.question_id:
            return NOT_OPEN
        if at >= self.question.closes_at:
            return "The response window has closed."
        if user_id in self.answered:
            return "You have already answered this question."
        # question_type decided at delivery whether it has options, and the
        # student is held to that, not to whichever field they happened to set.
        options = self.question.options
        if options:
            if answer.selected_option is None:
                return "Choose one of the options."
            if answer.selected_option >= len(options):
                return "That option is not one of the choices."
        elif answer.free_text is None:
            return "Answer this question in your own words."
        return None

    def accept(self, user_id: UUID, at: datetime) -> None:
        self.answered.add(user_id)
        window = (self.question.closes_at - self.opened_at).total_seconds()
        if window > 0:
            self.timing[user_id] = (at - self.opened_at).total_seconds() / window

    def withdraw(self, user_id: UUID) -> None:
        """Forget an answer the recorder could not store, so it can be sent again."""
        self.answered.discard(user_id)
        self.timing.pop(user_id, None)


class LiveSession:
    def __init__(
        self,
        session_id: UUID,
        delivered: int,
        first_wait: timedelta | None,
        rooms: Rooms,
        paused: bool = False,
    ) -> None:
        self.session_id = session_id
        # Every change to the open question, the pause and the prompts
        # happens under this lock, and so do the events announcing them, so
        # question.closed can never overtake the question.delivered it closes.
        self.lock = asyncio.Lock()
        self.open: _OpenQuestion | None = None
        self.delivered = delivered
        self.countdown = Countdown(first_wait, paused=paused)
        self.cycle: asyncio.Task[None] | None = None
        self.attention = Attention(session_id)
        self.alerts: list[ClassComprehensionAlert] = []
        # Attention minutes being stored. Not awaited by the socket that ended
        # the minute, so a slow store never delays that student's next answer;
        # the end of the session waits for them.
        self.storing: set[asyncio.Task[None]] = set()
        self.rooms = rooms
        # The timer that looks at signals and rooms. Started by the first of
        # either, so a class with neither has no timer.
        self.watch: asyncio.Task[None] | None = None


class Classroom:
    """Every live session this process is running. One instance per process,
    for the same reason there is one hub."""

    def __init__(
        self,
        events: SessionHub = hub,
        sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory,
        settings: Callable[[], Settings] = get_settings,
        rng: random.Random | None = None,
        consents: ConsentRegistry | None = None,
    ) -> None:
        self._hub = events
        # What each student has consented to be monitored for. Cyber 1's
        # rules for it are in consent.py.
        self.consents = consents if consents is not None else ConsentRegistry()
        self.accommodations = Accommodations()
        self._random = rng or random.Random()
        self._sessions = sessions
        self._settings = settings
        self._live: dict[UUID, LiveSession] = {}
        self._finished: OrderedDict[UUID, SessionStatus] = OrderedDict()
        self.recorder: ResponseRecorder | None = None
        self.prompt_recorder: PromptRecorder | None = None
        self.close_recorder: CloseRecorder | None = None
        self.participant_recorder: ParticipantRecorder | None = None
        self.comprehension_source: ComprehensionSource | None = None
        self.alert_recorder: AlertRecorder | None = None
        self.attention_recorder: AttentionRecorder | None = None

    def _next_wait(self) -> timedelta | None:
        """A fresh random wait before the next scheduled question, or None
        when the cycle is off and the lecturer sends every question."""
        settings = self._settings()
        low = settings.checkpoint_interval_min_seconds
        high = settings.checkpoint_interval_max_seconds
        if high <= 0:
            return None
        return timedelta(seconds=self._random.uniform(low, high))

    def check_wiring(self) -> None:
        """Say what a live session will not do in this deployment, at startup.

        Answers, closes, prompt outcomes, attendance, alerts and attention
        summaries are kept nowhere until AI 1, BBIS and Cyber 1 register their
        recorders, and a second worker would run a second cycle for every
        session. Development is told; production refuses to start rather than
        run a class that loses its answers.
        """
        problems = [
            f"no {name} is registered, so {what} not stored"
            for recorder, name, what in (
                (self.recorder, "ResponseRecorder", "answers are"),
                (self.prompt_recorder, "PromptRecorder", "prompt outcomes are"),
                (self.close_recorder, "CloseRecorder", "question closes are"),
                (self.participant_recorder, "ParticipantRecorder", "who attended is"),
                (self.alert_recorder, "AlertRecorder", "alerts are"),
                (self.attention_recorder, "AttentionRecorder", "attention summaries are"),
            )
            if recorder is None
        ]
        workers = os.environ.get(WORKERS_ENV, "1").strip() or "1"
        if not workers.isdigit() or int(workers) > 1:
            problems.append(
                f"{WORKERS_ENV}={workers}: live sessions need a single worker, or each "
                "worker runs its own question cycle for the same session, and reports, "
                "live consent and scores held in one worker's memory are missing from "
                "the others"
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

    @property
    def running_count(self) -> int:
        """How many sessions this process is running now. The retention purge
        stops between batches while this is above zero."""
        return len(self._live)

    def activate(self, session_id: UUID, delivered: int = 0, paused: bool = False) -> LiveSession:
        """Begin running a session: its cycle starts counting from now."""
        live = self._live.get(session_id)
        if live is None:
            live = self._live[session_id] = LiveSession(
                session_id,
                delivered,
                self._next_wait(),
                Rooms(RoomLimits.from_settings(self._settings())),
                paused,
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

    async def _running(self, db: AsyncSession, row: Session) -> LiveSession:
        """restore(), for a caller that cannot do anything with a session
        that is not running."""
        live = await self.restore(db, row)
        if live is None:
            raise ConflictError("The session is not running.", {"status": row.status})
        return live

    async def pause(self, db: AsyncSession, row: Session) -> None:
        """Record and apply a pause. The caller holds the row locked and has
        checked the session is active and running.

        No question goes out until it resumes, and no attention prompt. A
        question already open runs to the end of its window, so nobody loses
        an answer they were typing. The time left before the next scheduled
        question is kept for the resume.
        """
        live = await self._running(db, row)
        # The change is recorded and applied under the session's lock, so a
        # pause and a resume sent together are applied in the order the
        # database took them.
        async with live.lock:
            row.paused_at = datetime.now(UTC)
            await db.commit()
            live.countdown.pause()
            _cancel(live.cycle)
            live.cycle = None
            await self.announce(live.session_id, SessionStatus.ACTIVE)

    async def resume(self, db: AsyncSession, row: Session) -> None:
        """Record and apply the end of a pause. The next scheduled question
        comes after whatever was left of the wait when it paused."""
        live = await self._running(db, row)
        async with live.lock:
            row.paused_at = None
            await db.commit()
            if live.countdown.paused:
                left = live.countdown.resume()
                if live.open is None:
                    live.countdown.start(left if left is not None else self._next_wait())
                self._start_cycle(live)
            await self.announce(live.session_id, SessionStatus.ACTIVE)

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
        if live is None:
            await self.announce(session_id, status, delivered)
            self._hub.forget_session(session_id)
            return
        async with self._settled(live):
            open_ = live.open
            closed = await self._close_locked(live, QuestionCloseReason.SESSION_ENDED)
            withdrawn = live.attention.withdraw_all()
            windows = live.attention.windows.drain()
            # The last question still counts, but nobody is nudged in a class
            # that has ended.
            if open_ is not None:
                live.attention.score(*self._monitored_in(open_), open_.timing, _now())
        _cancel(live.cycle)
        _cancel(live.watch)
        for prompt in withdrawn:
            _cancel(prompt.expiry)
        await self.announce(session_id, status, delivered)
        # Before the session is forgotten, so the class can still be shown the
        # answer and the lecturer told. Independent of each other, and the
        # lecturer's request waits on them.
        await asyncio.gather(
            self._after_close(live, closed),
            self._record_windows(session_id, windows),
            *live.storing,
            *(self._record_prompt(p.outcome(PromptResult.EXPIRED)) for p in withdrawn),
        )
        self._hub.forget_session(session_id)

    async def shutdown(self) -> None:
        """Stop every timer this process owns. Sessions stay active in the
        database and resume in whichever process next touches them.

        Attention minutes already being stored are waited for, not cancelled:
        each is bounded by the recorder timeout, and cancelling one would lose
        a minute that was handed over before its commit."""
        tasks = []
        storing = [task for live in self._live.values() for task in live.storing]
        for live in self._live.values():
            tasks.append(live.cycle)
            tasks.append(live.watch)
            if live.open is not None:
                tasks.append(live.open.closer)
            tasks.extend(prompt.expiry for prompt in live.attention.pending())
        self._live.clear()
        for task in tasks:
            _cancel(task)
        for task in tasks:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        await asyncio.gather(*storing, return_exceptions=True)

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
            active_question_id=live.open.question.question_id if live and live.open else None,
            questions_delivered=live.delivered if live else delivered,
            paused=bool(live and live.countdown.paused),
        )

    async def announce(self, session_id: UUID, status: SessionStatus, delivered: int = 0) -> None:
        """Tell the session its current state."""
        await self._hub.broadcast(
            session_id,
            ServerEventType.SESSION_STATE,
            self.state(session_id, status, delivered).model_dump(mode="json"),
        )

    async def arrived(
        self, session_id: UUID, user_id: UUID, role: Role | None, recorded: SessionStatus
    ) -> None:
        """A socket has joined the session. Every student socket is recorded
        as attendance, since reconnecting belongs in the record; a student's
        first one changes who is present, which connected staff are told.

        recorded is the session's status when the socket was admitted.
        """
        if role is not Role.STUDENT:
            return
        if self._hub.connection_count(session_id, user_id) == 1:
            await self.announce_presence(session_id, recorded)
        if self.participant_recorder is not None:
            await best_effort(
                self.participant_recorder.record_join(Attendance(session_id, user_id, _now())),
                "record a student joining",
                session_id,
            )

    async def departed(
        self, session_id: UUID, user_id: UUID, role: Role | None, recorded: SessionStatus
    ) -> None:
        """A socket that arrived has left the session, whoever closed it.
        Only a student's last socket means they have left the class: one who
        closes one of two tabs has not, and the stored record, which counts
        joins, cannot tell."""
        if role is not Role.STUDENT or self._hub.connection_count(session_id, user_id) > 0:
            return
        await self.announce_presence(session_id, recorded)
        if self.participant_recorder is not None:
            await best_effort(
                self.participant_recorder.record_leave(Attendance(session_id, user_id, _now())),
                "record a student leaving",
                session_id,
            )

    async def announce_presence(self, session_id: UUID, recorded: SessionStatus) -> None:
        """Tell connected staff the unique student count."""
        if session_id in self._live:
            status = SessionStatus.ACTIVE
        elif session_id in self._finished:
            return
        else:
            status = recorded
        await self._tell_staff(
            session_id, ServerEventType.SESSION_STATE, _json(self.state(session_id, status))
        )

    async def _tell_staff(self, session_id: UUID, event: ServerEventType, data: dict) -> None:
        """Send one event to every member of staff connected to the session."""
        for staff_id in self._hub.staff_ids(session_id):
            await self._hub.send_to_user(session_id, staff_id, event, data)

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

        now = _now()
        open_ = live.open
        if open_ is not None and now < open_.question.closes_at:
            if role is not Role.STUDENT:
                # The lecturer's panel shows the question and its timer.
                events.append((ServerEventType.QUESTION_DELIVERED, _json(open_.question)))
            elif user_id not in open_.answered:
                # Shown the question, so expected to answer it.
                open_.present.add(user_id)
                events.append((ServerEventType.QUESTION_DELIVERED, _json(open_.question)))

        prompt = live.attention.waiting(user_id, now)
        if prompt is not None:
            events.append((ServerEventType.PROMPT_ATTENTION, _json(prompt.payload)))
        if role in (Role.LECTURER, Role.ADMIN):
            # A panel opened or refreshed mid-class shows the rooms as they
            # are, and is told of each change after that.
            for room in live.rooms.statuses(now, self._hub.student_ids(session_id)):
                events.append((ServerEventType.ROOM_STATUS, _json(room)))
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
        live = await self._running(db, row)
        async with live.lock:
            if live.countdown.paused:
                raise ConflictError(
                    "The session is paused. Resume it to deliver a question.",
                    {"session_id": str(row.session_id)},
                )
            if live.open is not None:
                raise ConflictError(
                    "A question is already open.",
                    {"question_id": str(live.open.question.question_id)},
                )
            now = _now()
            window = self._window
            closes_at = now + window
            window_seconds = int(window.total_seconds())
            question = await SessionRepository(db).claim_for_delivery(
                row,
                question_id,
                delivered_at=now,
                closes_at=closes_at,
                window_seconds=window_seconds,
            )
            if question is None:
                return None
            payload = QuestionDeliveredPayload(
                question_id=question.question_id,
                prompt=question.question_text,
                # question_type decides how it is answered, not whether
                # options happen to be set. Reading it from the options alone
                # turned a multiple choice question whose choices were missing
                # into a free-text one, and the student was told to answer in
                # their own words while their screen offered buttons. The
                # repository will not hand out such a question, and this
                # agrees with it.
                options=question.options if question.question_type == QuestionType.MCQ else None,
                closes_at=closes_at,
                window_seconds=window_seconds,
                source_slide=question.source_slide,
            )
            # The claim and its delivery record are committed before anyone
            # is told, so a delivered question is never missing from the
            # session's history, and its close always has a row to complete.
            await db.commit()

            live.open = _OpenQuestion(
                payload, present=self._hub.student_ids(row.session_id), opened_at=now
            )
            live.delivered += 1
            # Whatever was due is discarded, manual or scheduled: the next
            # wait is drawn when this question closes, so the cycle never
            # sends another moments after the lecturer did.
            live.countdown.start(None)
            await self._hub.broadcast(
                row.session_id, ServerEventType.QUESTION_DELIVERED, _json(payload)
            )
            live.open.closer = asyncio.create_task(
                self._close_when_due(live, live.open),
                name=f"response-window-{question.question_id}",
            )
        return payload

    async def _close_when_due(self, live: LiveSession, open_: _OpenQuestion) -> None:
        await _sleep_until(open_.question.closes_at)
        closed = None
        async with self._settled(live):
            if live.open is open_:
                closed = await self._close_locked(live, QuestionCloseReason.WINDOW_ELAPSED)
                # The next wait starts now, not at the delivery, so the
                # response window is not taken out of the teaching time.
                live.countdown.start(self._next_wait())
                await self._nudge_absent_locked(live, open_)
                await self._score_engagement_locked(live, open_)
        await self._after_close(live, closed)

    @contextlib.asynccontextmanager
    async def _settled(self, live: LiveSession) -> AsyncIterator[None]:
        """Hold the session's lock once no answer to the open question is
        still being stored, so a close announces, scores and stores only the
        answers that were kept.

        The wait is outside the lock, since a write that fails takes it to
        withdraw the answer, and each write is bounded by
        RECORD_TIMEOUT_SECONDS. It does not reopen the window: an answer
        arriving after closes_at is refused whether or not the close has run.
        """
        while True:
            open_ = live.open
            pending = [saved for saved in open_.saving if not saved.done()] if open_ else []
            if pending:
                await asyncio.wait(pending)
                continue
            async with live.lock:
                open_ = live.open
                if open_ is None or all(saved.done() for saved in open_.saving):
                    yield
                    return

    async def _close_locked(
        self, live: LiveSession, reason: QuestionCloseReason
    ) -> ClosedQuestion | None:
        """Close the open question and say so. Returns what the close
        recorder is to be given once the caller releases the lock."""
        open_ = live.open
        if open_ is None:
            return None
        live.open = None
        _cancel(open_.closer)
        payload = QuestionClosedPayload(
            question_id=open_.question.question_id,
            reason=reason,
            respondents=len(open_.answered),
            eligible=len(open_.eligible),
        )
        await self._hub.broadcast(live.session_id, ServerEventType.QUESTION_CLOSED, _json(payload))
        return ClosedQuestion(
            session_id=live.session_id,
            question_id=open_.question.question_id,
            reason=reason,
            closed_at=_now(),
            eligible=frozenset(open_.eligible),
            answered=frozenset(open_.answered),
        )

    async def _run_cycle(self, live: LiveSession) -> None:
        """Deliver the next staged question whenever one falls due."""
        while True:
            if not await live.countdown.elapsed():
                continue
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
                live.countdown.start(self._next_wait())

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
            if live.open is None and live.countdown.due is None:
                live.countdown.start(self._next_wait())
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
        received_at = _now()
        reason, feedback = await self._accept(session_id, user_id, role, answer, received_at)
        receipt = AnswerReceiptPayload(
            question_id=answer.question_id,
            accepted=reason is None,
            received_at=received_at,
            reason=reason,
        )
        await self._hub.send_to_user(
            session_id, user_id, ServerEventType.ANSWER_RECEIPT, _json(receipt)
        )
        if feedback is not None:
            await self._hub.send_to_user(
                session_id, user_id, ServerEventType.FEEDBACK_RESULT, _json(feedback)
            )
        return receipt

    async def _accept(
        self,
        session_id: UUID,
        user_id: UUID,
        role: Role | None,
        answer: AnswerSubmitPayload,
        received_at: datetime,
    ) -> tuple[str | None, FeedbackResultPayload | None]:
        """Why the answer was refused, or None and the recorder's feedback."""
        if role is not Role.STUDENT:
            return "Only students answer questions.", None
        live = self._live.get(session_id)
        if live is None:
            return NOT_OPEN, None
        async with live.lock:
            open_ = live.open
            reason = NOT_OPEN if open_ is None else open_.refusal(user_id, answer, received_at)
            if reason is not None:
                return reason, None
            open_.accept(user_id, received_at)
            # Answering is the task a breakout room is doing.
            live.rooms.interacted(user_id)
            if self.recorder is None:
                return None, None
            saved = asyncio.get_running_loop().create_future()
            open_.saving.append(saved)

        try:
            async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
                return None, await self.recorder.record(
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
                open_.withdraw(user_id)
                still_open = live.open is open_ and _now() < open_.question.closes_at
            if still_open:
                return "Your answer could not be saved. Please submit it again.", None
            return "Your answer could not be saved.", None
        finally:
            # After any withdrawal, so a close waiting on this sees the answer
            # gone.
            if not saved.done():
                saved.set_result(None)

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
        message = checked_message(message)
        live = self._live.get(session_id)
        if live is None:
            return None
        async with live.lock:
            return await self._prompt_locked(live, user_id, message)

    async def _prompt_locked(
        self, live: LiveSession, user_id: UUID, message: str
    ) -> AttentionPromptPayload | None:
        if live.countdown.paused or user_id not in self._hub.student_ids(live.session_id):
            return None
        # An attention prompt is part of engagement monitoring, which the
        # student may decline without leaving the class.
        if not self.consents.monitored(user_id):
            return None
        if live.open is not None and user_id not in live.open.answered:
            return None
        settings = self._settings()
        prompt = live.attention.issue(
            user_id,
            message,
            limit=settings.dynamic_prompt_max_per_student,
            ttl=timedelta(seconds=settings.attention_prompt_ttl_seconds),
            now=_now(),
        )
        if prompt is None:
            return None
        prompt.expiry = asyncio.create_task(
            self._expire_when_due(live, prompt),
            name=f"attention-prompt-{prompt.payload.prompt_id}",
        )
        await self._hub.send_to_user(
            live.session_id, user_id, ServerEventType.PROMPT_ATTENTION, _json(prompt.payload)
        )
        return prompt.payload

    async def _nudge_absent_locked(self, live: LiveSession, closed: _OpenQuestion) -> None:
        """Count the questions each student was shown and let pass, and nudge
        one who has missed attention_prompt_after_missed_questions in a row.

        This is the scheduler's own trigger, from what it already knows.
        Engagement scoring can prompt for its own reasons through
        prompt_student(); both obey the same limits.
        """
        threshold = self._settings().attention_prompt_after_missed_questions
        due = live.attention.count_missed(closed.present, closed.answered, threshold)
        for user_id, missed in due.items():
            await self._prompt_locked(live, user_id, _missed_message(missed))

    async def acknowledge_prompt(
        self, session_id: UUID, user_id: UUID, ack: PromptAckPayload
    ) -> bool:
        """A student's answer to their own prompt. False when that prompt is
        not waiting on this student: unknown, someone else's, already
        answered or expired."""
        live = self._live.get(session_id)
        if live is None:
            return False
        now = _now()
        async with live.lock:
            prompt = live.attention.answer(user_id, ack.prompt_id, dismissed=ack.dismissed, now=now)
            if prompt is None:
                return False
            _cancel(prompt.expiry)
        result = PromptResult.DISMISSED if ack.dismissed else PromptResult.ACKNOWLEDGED
        await self._record_prompt(prompt.outcome(result, now))
        return True

    async def _expire_when_due(self, live: LiveSession, prompt: Prompt) -> None:
        await _sleep_until(prompt.payload.expires_at)
        async with live.lock:
            expired = live.attention.expire(prompt)
        if expired:
            await self._record_prompt(prompt.outcome(PromptResult.EXPIRED))

    # -- engagement and comprehension (Cyber 1) --------------------------------

    async def record_attention(
        self, session_id: UUID, user_id: UUID, signal: AttentionSignalPayload
    ) -> bool:
        """Keep a student's client attention signal for their next engagement
        score and their current minute, less whatever their consent does not
        cover, count its voice reading towards their breakout room, and store
        the minutes that are now over. False when the session is not running
        here, the sender is not a student connected to it, or they have not
        consented to engagement monitoring. A signal sent too soon after the
        last is dropped quietly, and still returns True."""
        live = self._live.get(session_id)
        if live is None or user_id not in self._hub.student_ids(session_id):
            return False
        kept = permitted_signal(signal, self.consents.granted(user_id))
        if kept is None:
            return False
        async with live.lock:
            if self._live.get(session_id) is not live:
                return False
            now = _now()
            held, finished = live.attention.observe(user_id, kept, now)
            if held is not None:
                live.rooms.heard(user_id, held.speaking, now)
                self._start_watch(live)
        if finished:
            task = asyncio.create_task(self._record_windows(session_id, finished))
            live.storing.add(task)
            task.add_done_callback(live.storing.discard)
        return True

    # -- breakout rooms and the watch (Phase 6) ---------------------------------

    async def confirm_room(
        self, session_id: UUID, user_id: UUID, confirm: RoomConfirmPayload
    ) -> Refusal | None:
        """Put a student in the breakout room they say they are in, and tell
        the lecturer how the rooms now stand. Returns why it was refused, or
        None.

        The student's word is the mapping. They move by confirming another
        room; a room left empty disappears from the lecturer's panel.
        """
        live = self._live.get(session_id)
        if live is None or user_id not in self._hub.student_ids(session_id):
            return Refusal.NOT_IN_SESSION
        async with live.lock:
            if self._live.get(session_id) is not live:
                return Refusal.NOT_IN_SESSION
            refused = live.rooms.confirm(user_id, confirm.room_label)
            if refused is not None:
                return refused
            self._start_watch(live)
            alerts = await self._tell_rooms_locked(live, _now())
        # A member arriving can be what first shows a room has been silent
        # too long, so an alert may fall due here as well as in the watch.
        for alert in alerts:
            await self._raise_room_alert(alert)
        return None

    def rooms(self, session_id: UUID) -> list[RoomStatusPayload]:
        """How each breakout room of a session this process is running is
        doing now, in label order."""
        live = self._live.get(session_id)
        if live is None:
            return []
        return live.rooms.statuses(_now(), self._hub.student_ids(session_id))

    def _start_watch(self, live: LiveSession) -> None:
        if live.watch is None or live.watch.done():
            live.watch = asyncio.create_task(
                self._watch(live), name=f"signal-watch-{live.session_id}"
            )

    async def _watch(self, live: LiveSession) -> None:
        """Look at the session's signals and rooms every signal_watch_seconds
        until it ends. One pass failing is logged and the next still runs."""
        while True:
            await asyncio.sleep(self._settings().signal_watch_seconds)
            if self._live.get(live.session_id) is not live:
                return
            try:
                await self.watch_once(live)
            except Exception:
                log.exception("attention watch failed for session %s", live.session_id)

    async def watch_once(self, live: LiveSession) -> None:
        """One pass of the watch: rescore, prompt, and tell the lecturer about
        the rooms, then raise any room alert once the lock is released."""
        async with live.lock:
            if self._live.get(live.session_id) is not live:
                return
            now = _now()
            await self._watch_signals_locked(live, now)
            alerts = await self._tell_rooms_locked(live, now)
        for alert in alerts:
            await self._raise_room_alert(alert)

    async def _watch_signals_locked(self, live: LiveSession, now: datetime) -> None:
        """Rescore every student whose device has reported, and send a
        private prompt to one whose signals have stayed low.

        A prompt needs all of: enough of the window covered by signals, the
        signals themselves low, engagement scoring agreeing on more than one
        kind of evidence (Cyber 1's rule), and no prompt from signals within
        the cooldown. _prompt_locked then applies the limits every prompt
        obeys: not while paused, not over a question the student still has to
        answer, one at a time, and no more than the cap. The prompt goes to
        the student alone; staff are not told.
        """
        settings = self._settings()
        connected = self._hub.student_ids(live.session_id)
        needed = settings.refocus_min_signal_seconds
        cooldown = timedelta(seconds=settings.refocus_cooldown_seconds)
        accommodated = self.accommodations.members()
        for user_id in live.attention.observed():
            # Withdrawing monitoring already drops the student's signals
            # (Attention.forget), so they are not observed; this is the
            # second lock on that door.
            if user_id not in connected or not self.consents.monitored(user_id):
                continue
            scored = live.attention.rescore(user_id, now, user_id in accommodated)
            signal = live.attention.signal(user_id, now)
            if (
                needed > 0
                and signal is not None
                and signal.window_seconds >= needed
                and signals_low(signal)
                and should_send_dynamic_prompt(scored.engagement)
                and live.attention.refocus_due(user_id, now, cooldown)
                and await self._prompt_locked(live, user_id, REFOCUS_PROMPT_MESSAGE) is not None
            ):
                live.attention.refocused(user_id, now)

    async def _tell_rooms_locked(self, live: LiveSession, now: datetime) -> list[RoomAlert]:
        """Tell connected staff about every room whose status has changed,
        and return the alerts that have fallen due, to be raised once the
        lock is released."""
        news = live.rooms.news(live.session_id, now, self._hub.student_ids(live.session_id))
        for room in news.changed:
            await self._tell_staff(live.session_id, ServerEventType.ROOM_STATUS, _json(room))
        return news.alerts

    async def _raise_room_alert(self, alert: RoomAlert) -> None:
        """Keep a room alert, then tell the lecturer. As with a comprehension
        alert, a store that fails does not cost the lecturer the alert."""
        if self.alert_recorder is not None:
            await best_effort(
                self.alert_recorder.record_room_alert(alert), "store a room alert", alert.session_id
            )
        await self._tell_staff(
            alert.session_id,
            ServerEventType.ALERT_RAISED,
            _json(_raised(AlertKind.BREAKOUT_INACTIVE, alert)),
        )

    def _monitored_in(self, question: _OpenQuestion) -> tuple[set[UUID], set[UUID]]:
        """Who was shown a question and who answered it, among the students
        engagement scoring may consider."""
        monitored = {u for u in question.eligible if self.consents.monitored(u)}
        return question.present & monitored, question.answered & monitored

    def admit_consents(
        self, user_id: UUID, granted: Iterable[ConsentType], read_at: int
    ) -> frozenset[ConsentType]:
        """Record what a user joining a class has consented to, as read from
        the store while the registry's version was read_at. A decision
        recorded meanwhile wins. Returns what now holds."""
        return self.consents.admit(user_id, granted, read_at)

    async def withdraw_consent(self, user_id: UUID, consent: ConsentType) -> None:
        """Stop acting on a consent the user has just withdrawn, in every class
        this process runs, as the consent contract promises: at once, not at
        their next reconnect.

        Engagement monitoring: everything kept about the student's engagement
        is dropped and any prompt waiting on them is taken down. Camera or
        microphone: those parts of their stored signal are dropped. Terms:
        their session sockets are closed.

        A grant is not applied here. The consent route reads it back from the
        store and admits it (admit_consents) once it has committed together
        with its audit record, so no class ever acts on a decision the
        database might not keep.
        """
        held = self.consents.set(user_id, self.consents.granted(user_id) - {consent})
        withdrawn: list[Prompt] = []
        for live in list(self._live.values()):
            async with live.lock:
                if ConsentType.ENGAGEMENT_MONITORING not in held:
                    prompt = live.attention.forget(user_id)
                    if prompt is not None:
                        withdrawn.append(prompt)
                else:
                    live.attention.restrict_signal(
                        user_id, lambda signal: permitted_signal(signal, held)
                    )
                    if ConsentType.CAMERA not in held:
                        live.attention.purge_visual(user_id)
                # A room's voice activity comes from the same signals, so
                # what was heard from this student goes with the consent.
                # They stay in the room they confirmed.
                if not {ConsentType.ENGAGEMENT_MONITORING, ConsentType.MICROPHONE} <= held:
                    live.rooms.unhear(user_id)
        for prompt in withdrawn:
            _cancel(prompt.expiry)
        if consent is ConsentType.TERMS:
            await self._hub.close_user_sessions(user_id, CLOSE_CONSENT, "consent withdrawn")

    async def _score_engagement_locked(self, live: LiveSession, closed: _OpenQuestion) -> None:
        """Rescore everyone who was shown the question that just closed, and
        nudge those engagement scoring says need it. prompt_student's limits
        (cap, pause, one at a time, connected) still apply."""
        shown, answered = self._monitored_in(closed)
        for scored in live.attention.score(
            shown, answered, closed.timing, _now(), self.accommodations.members()
        ):
            if should_send_dynamic_prompt(scored.engagement):
                await self._prompt_locked(live, scored.user_id, ENGAGEMENT_PROMPT_MESSAGE)

    async def _check_comprehension(self, live: LiveSession, closed: ClosedQuestion) -> None:
        """Raise a class comprehension alert to the lecturer once enough of
        the class has been classified partial or struggling on a question."""
        if self.comprehension_source is None:
            return
        found = await best_effort(
            self.comprehension_source.question_labels(closed.session_id, closed.question_id),
            "read comprehension",
            closed.session_id,
        )
        if found is None:
            return
        settings = self._settings()
        decision = evaluate_comprehension_alert(
            found.labels,
            min_respondents=settings.comprehension_alert_min_respondents,
            threshold=settings.comprehension_alert_threshold,
        )
        if not decision.should_alert or decision.correct_ratio is None:
            return
        explained = _explain_comprehension_alert(found, closed, settings)
        stored = ClassComprehensionAlert(
            alert_id=uuid4(),
            session_id=closed.session_id,
            question_id=closed.question_id,
            topic=found.topic,
            correct_ratio=decision.correct_ratio,
            respondents=decision.respondents,
            threshold=settings.comprehension_alert_threshold,
            raised_at=_now(),
            message=explained.message,
            reason=explained.reason,
            confidence=explained.confidence,
            explanation=explained.explanation,
            explanation_source=explained.explanation_source,
            confidence_reasons=list(explained.confidence_reasons),
            recommendation=explained.recommendation,
        )
        live.alerts.append(stored)
        # Kept before the lecturer is told, so the alert they can click is one
        # that exists. A failure is logged and the alert still goes out: a
        # lecturer who is told late, or not at all, helps nobody.
        if self.alert_recorder is not None:
            await best_effort(
                self.alert_recorder.record_alert(stored), "store an alert", closed.session_id
            )
        await self._tell_staff(
            closed.session_id,
            ServerEventType.ALERT_RAISED,
            _json(_raised(AlertKind.TOPIC_DIFFICULTY, stored)),
        )

    def engagement(self, session_id: UUID) -> list[ScoredStudent]:
        """The latest engagement score of each student scored in a session this
        process is running, by user id. The caller resolves the student id."""
        live = self._live.get(session_id)
        if live is None:
            return []
        return [s for s in live.attention.scores() if self.consents.monitored(s.user_id)]

    def alerts(self, session_id: UUID) -> list[ClassComprehensionAlert]:
        live = self._live.get(session_id)
        return list(live.alerts) if live is not None else []

    # -- recording ------------------------------------------------------------

    # These run once the session's lock is released, so a slow store never
    # holds up a pause, a delivery or the next answer.

    async def _record_prompt(self, outcome: PromptOutcome) -> None:
        if self.prompt_recorder is not None:
            await best_effort(
                self.prompt_recorder.record_prompt(outcome),
                "record a prompt outcome",
                outcome.session_id,
            )

    async def _record_windows(self, session_id: UUID, windows: list[AttentionWindow]) -> None:
        if windows and self.attention_recorder is not None:
            await best_effort(
                self.attention_recorder.record_windows(windows),
                "record attention summaries",
                session_id,
            )

    async def _after_close(self, live: LiveSession, closed: ClosedQuestion | None) -> None:
        """Store a close and reveal its answer, and alert the lecturer if the
        class did not follow. Independent, so neither waits on the other."""
        if closed is not None:
            await asyncio.gather(
                self._record_close(closed), self._check_comprehension(live, closed)
            )

    async def _record_close(self, closed: ClosedQuestion) -> None:
        if self.close_recorder is None:
            return
        reveals = await best_effort(
            self.close_recorder.record_close(closed),
            "record a question close",
            closed.session_id,
        )
        # Outside the recorder's budget: the close is stored by now, and each
        # send is bounded by the hub, so a stalled socket costs its own reveal.
        for user_id, reveal in (reveals or {}).items():
            await self._hub.send_to_user(
                closed.session_id, user_id, ServerEventType.FEEDBACK_RESULT, _json(reveal)
            )


def _now() -> datetime:
    return datetime.now(UTC)


def _json(payload: object) -> dict:
    return payload.model_dump(mode="json")  # type: ignore[attr-defined]


async def _sleep_until(when: datetime) -> None:
    await asyncio.sleep(max((when - _now()).total_seconds(), 0.0))


def _explain_comprehension_alert(
    found: QuestionComprehension, closed: ClosedQuestion, settings: Settings
) -> AlertExplanation:
    """The reason, explanation and recommendation for a class comprehension alert.

    Explaining is never allowed to cost the lecturer the alert: if it fails for
    any reason, the alert goes out with the generic fallback instead, which
    says so, rather than not going out or going out with nothing to read.
    """
    try:
        return explain_topic_difficulty(
            TopicEvidence(
                labels=found.labels,
                eligible=len(closed.eligible),
                min_respondents=settings.comprehension_alert_min_respondents,
                threshold=settings.comprehension_alert_threshold,
                confidences=found.confidences,
                topic=found.topic,
                source_slide=found.source_slide,
            )
        )
    except Exception:
        log.exception("could not explain a comprehension alert in session %s", closed.session_id)
        return fallback_explanation(AlertKind.TOPIC_DIFFICULTY)


class _Raisable(Protocol):
    """What every alert kept for a lecturer carries, whatever raised it."""

    alert_id: UUID
    message: str
    reason: str
    confidence: float
    explanation: str
    explanation_source: str
    confidence_reasons: list[str]
    recommendation: str


def _raised(kind: AlertKind, alert: _Raisable) -> AlertRaisedPayload:
    """The alert.raised payload for an alert that has been kept."""
    return AlertRaisedPayload(
        alert_id=alert.alert_id,
        kind=kind,
        message=alert.message,
        reason=alert.reason,
        confidence=alert.confidence,
        explanation=alert.explanation,
        explanation_source=alert.explanation_source,  # type: ignore[arg-type]
        confidence_reasons=list(alert.confidence_reasons),
        recommendation=alert.recommendation,
    )


def _missed_message(missed: int) -> str:
    return f"You have missed the last {missed} questions. Still with us?"


def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is not None and task is not asyncio.current_task():
        task.cancel()


classroom = Classroom()
