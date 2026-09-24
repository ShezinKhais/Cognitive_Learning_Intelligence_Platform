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

Answers, question closes and prompt outcomes are handed to the recorders in
recorders.py. Feedback on an answer is what the ResponseRecorder returns,
sent here after the receipt, and the answer can be revealed from the
CloseRecorder once the window is over.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.errors import ConflictError
from app.models.session import Session
from app.realtime.attention import Attention, Prompt, checked_message
from app.realtime.countdown import Countdown
from app.realtime.hub import SessionHub, hub
from app.realtime.recorders import (
    RECORD_TIMEOUT_SECONDS,
    ClosedQuestion,
    CloseRecorder,
    PromptOutcome,
    PromptRecorder,
    PromptResult,
    ResponseRecorder,
    Submission,
)
from app.repositories.session_repository import SessionRepository
from app.schemas.content import QuestionType
from app.schemas.events import (
    AnswerReceiptPayload,
    AnswerSubmitPayload,
    AttentionPromptPayload,
    FeedbackResultPayload,
    PromptAckPayload,
    QuestionClosedPayload,
    QuestionCloseReason,
    QuestionDeliveredPayload,
    ServerEventType,
    SessionStatePayload,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus

log = logging.getLogger("clip.classroom")

# Sessions this process has ended, remembered so a socket admitted a moment
# before the end cannot bring the session back to life or be told it is still
# waiting to start. Bounded because a process runs for weeks.
MAX_FINISHED_SESSIONS = 1024

# uvicorn and gunicorn read their worker count from this.
WORKERS_ENV = "WEB_CONCURRENCY"

NOT_OPEN = "This question is not open."


@dataclass
class _OpenQuestion:
    question: QuestionDeliveredPayload
    # Students who were shown the question: connected when it went out, or
    # given it on joining. Anyone who answers counts as eligible too.
    present: set[UUID]
    answered: set[UUID] = field(default_factory=set)
    closer: asyncio.Task[None] | None = None

    def refusal(self, user_id: UUID, answer: AnswerSubmitPayload, at: datetime) -> str | None:
        """Why this answer to this question cannot be accepted, or None."""
        if answer.question_id != self.question.question_id:
            return NOT_OPEN
        if at >= self.question.closes_at:
            return "The response window has closed."
        if user_id in self.answered:
            return "You have already answered this question."
        options = self.question.options
        if not options:
            return "Answer this question in your own words." if answer.free_text is None else None
        if answer.selected_option is None:
            return "Choose one of the options."
        if answer.selected_option >= len(options):
            return "That option is not one of the choices."
        return None


class LiveSession:
    def __init__(
        self, session_id: UUID, delivered: int, first_wait: timedelta | None, paused: bool
    ) -> None:
        self.session_id = session_id
        # Every change to the open question, the pause and the prompts
        # happens under this lock, and so do the events announcing them, so
        # question.closed can never overtake the question.delivered it closes.
        self.lock = asyncio.Lock()
        self.open: _OpenQuestion | None = None
        self.delivered = delivered
        # Pausing the session holds its countdown.
        self.countdown = Countdown(first_wait, paused=paused)
        self.cycle: asyncio.Task[None] | None = None
        self.attention = Attention(session_id)

    @property
    def paused(self) -> bool:
        return self.countdown.paused


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

        Answers and prompt outcomes are kept nowhere until AI 1 and BBIS
        register their recorders, and a second worker would run a second
        cycle for every session. Development is told; production refuses to
        start rather than run a class that loses its answers.
        """
        problems = [
            f"no {name} is registered, so {what} are not stored"
            for recorder, name, what in (
                (self.recorder, "ResponseRecorder", "answers"),
                (self.prompt_recorder, "PromptRecorder", "prompt outcomes"),
                (self.close_recorder, "CloseRecorder", "question closes"),
            )
            if recorder is None
        ]
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

    async def _running(self, db: AsyncSession, row: Session) -> LiveSession:
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
            if live.paused:
                left = live.countdown.resume()
                # While a question is open its close starts the next wait.
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
        closed = None
        withdrawn: list[Prompt] = []
        if live is not None:
            async with live.lock:
                closed = await self._close_locked(live, QuestionCloseReason.SESSION_ENDED)
                withdrawn = live.attention.withdraw_all()
                for prompt in withdrawn:
                    _cancel(prompt.expiry)
            _cancel(live.cycle)
        await self.announce(session_id, status, delivered)
        self._hub.forget_session(session_id)
        await asyncio.gather(
            self._record_close(closed),
            *(self._record_prompt(prompt.outcome(PromptResult.EXPIRED)) for prompt in withdrawn),
        )

    async def shutdown(self) -> None:
        """Stop every timer this process owns. Sessions stay active in the
        database and resume in whichever process next touches them."""
        tasks = []
        for live in self._live.values():
            tasks.append(live.cycle)
            if live.open is not None:
                tasks.append(live.open.closer)
            tasks.extend(prompt.expiry for prompt in live.attention.withdraw_all())
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
            active_question_id=live.open.question.question_id if live and live.open else None,
            questions_delivered=live.delivered if live else delivered,
            paused=bool(live and live.paused),
        )

    async def announce(self, session_id: UUID, status: SessionStatus, delivered: int = 0) -> None:
        """Tell the session its current state, as after a start."""
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
        if open_ is not None and now < open_.question.closes_at:
            delivered = (ServerEventType.QUESTION_DELIVERED, open_.question.model_dump(mode="json"))
            if role is not Role.STUDENT:
                # The lecturer's panel shows the question and its timer.
                events.append(delivered)
            elif user_id not in open_.answered:
                # Shown the question, so expected to answer it.
                open_.present.add(user_id)
                events.append(delivered)

        prompt = live.attention.waiting(user_id, now)
        if prompt is not None:
            waiting = prompt.payload.model_dump(mode="json")
            events.append((ServerEventType.PROMPT_ATTENTION, waiting))
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
            if live.paused:
                raise ConflictError(
                    "The session is paused. Resume it to deliver a question.",
                    {"session_id": str(row.session_id)},
                )
            if live.open is not None:
                raise ConflictError(
                    "A question is already open.",
                    {"question_id": str(live.open.question.question_id)},
                )
            question = await SessionRepository(db).claim_for_delivery(row, question_id)
            if question is None:
                return None
            window = self._window
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
                closes_at=datetime.now(UTC) + window,
                window_seconds=int(window.total_seconds()),
                source_slide=question.source_slide,
            )
            # Recorded before anyone is told, so a delivered question is
            # never missing from the session's history.
            await db.commit()

            live.open = _OpenQuestion(payload, present=self._hub.student_ids(row.session_id))
            live.delivered += 1
            # Whatever was due is discarded, manual or scheduled: the next
            # wait is drawn when this question closes, so the cycle never
            # sends another moments after the lecturer did.
            live.countdown.start(None)
            await self._hub.broadcast(
                row.session_id, ServerEventType.QUESTION_DELIVERED, payload.model_dump(mode="json")
            )
            live.open.closer = asyncio.create_task(
                self._close_when_due(live, live.open),
                name=f"response-window-{question.question_id}",
            )
        return payload

    async def _close_when_due(self, live: LiveSession, open_: _OpenQuestion) -> None:
        await _sleep_until(open_.question.closes_at)
        closed = None
        async with live.lock:
            if live.open is open_:
                closed = await self._close_locked(live, QuestionCloseReason.WINDOW_ELAPSED)
                # The next wait starts now, not at the delivery, so the
                # response window is not taken out of the teaching time.
                live.countdown.start(self._next_wait())
                await self._nudge_absent_locked(live, open_)
        await self._record_close(closed)

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
        eligible = open_.present | open_.answered
        payload = QuestionClosedPayload(
            question_id=open_.question.question_id,
            reason=reason,
            respondents=len(open_.answered),
            eligible=len(eligible),
        )
        await self._hub.broadcast(
            live.session_id, ServerEventType.QUESTION_CLOSED, payload.model_dump(mode="json")
        )
        return ClosedQuestion(
            session_id=live.session_id,
            question_id=open_.question.question_id,
            reason=reason,
            closed_at=datetime.now(UTC),
            eligible=frozenset(eligible),
            answered=frozenset(open_.answered),
        )

    async def _run_cycle(self, live: LiveSession) -> None:
        """Deliver the next staged question whenever one falls due."""
        countdown = live.countdown
        while True:
            due = countdown.due
            countdown.changed.clear()
            if due is None:
                # A question is open; its close sets the next due time.
                await countdown.changed.wait()
                continue
            wait = (due - datetime.now(UTC)).total_seconds()
            if wait > 0:
                # Woken early when the due time changes; the loop measures
                # again. Not wait_for, which on Python 3.11 swallows a cancel
                # that lands as the wait completes, and the cycle outlives
                # the pause or shutdown that stopped it.
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(wait):
                        await countdown.changed.wait()
                continue
            countdown.start(None)
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
                countdown.start(self._next_wait())

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
        received_at = datetime.now(UTC)
        refusal, feedback = await self._accept(session_id, user_id, role, answer, received_at)
        receipt = AnswerReceiptPayload(
            question_id=answer.question_id,
            accepted=refusal is None,
            received_at=received_at,
            reason=refusal,
        )
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
            if open_ is None:
                return NOT_OPEN, None
            refusal = open_.refusal(user_id, answer, received_at)
            if refusal is not None:
                return refusal, None
            open_.answered.add(user_id)

        if self.recorder is None:
            return None, None
        submission = Submission(
            session_id=session_id,
            question_id=answer.question_id,
            user_id=user_id,
            selected_option=answer.selected_option,
            free_text=answer.free_text,
            client_elapsed_ms=answer.client_elapsed_ms,
            received_at=received_at,
        )
        try:
            async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
                return None, await self.recorder.record(submission)
        except Exception:
            log.exception("could not record an answer in session %s", session_id)
            async with live.lock:
                open_.answered.discard(user_id)
                still_open = live.open is open_ and datetime.now(UTC) < open_.question.closes_at
            if still_open:
                return "Your answer could not be saved. Please submit it again.", None
            return "Your answer could not be saved.", None

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
        if live.paused or user_id not in self._hub.student_ids(live.session_id):
            return None
        if live.open is not None and user_id not in live.open.answered:
            return None
        settings = self._settings()
        prompt = live.attention.issue(
            user_id,
            message,
            limit=settings.dynamic_prompt_max_per_student,
            ttl=timedelta(seconds=settings.attention_prompt_ttl_seconds),
            now=datetime.now(UTC),
        )
        if prompt is None:
            return None
        prompt.expiry = asyncio.create_task(
            self._expire_when_due(live, prompt),
            name=f"attention-prompt-{prompt.payload.prompt_id}",
        )
        await self._hub.send_to_user(
            live.session_id,
            user_id,
            ServerEventType.PROMPT_ATTENTION,
            prompt.payload.model_dump(mode="json"),
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
        due = live.attention.count_close(closed.present, closed.answered, threshold)
        for user_id, missed in due.items():
            message = f"You have missed the last {missed} questions. Still with us?"
            await self._prompt_locked(live, user_id, message)

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

    # -- recording ------------------------------------------------------------

    # Both run once the session's lock is released, so a slow store never
    # holds up a pause, a delivery or the next answer.

    async def _record_prompt(self, outcome: PromptOutcome) -> None:
        if self.prompt_recorder is not None:
            await _best_effort(
                self.prompt_recorder.record_prompt(outcome), "a prompt outcome", outcome.session_id
            )

    async def _record_close(self, closed: ClosedQuestion | None) -> None:
        if closed is not None and self.close_recorder is not None:
            await _best_effort(
                self.close_recorder.record_close(closed), "a question close", closed.session_id
            )


async def _best_effort(write: Awaitable[None], what: str, session_id: UUID) -> None:
    """Run a recorder whose failure changes nothing for the class: bounded by
    RECORD_TIMEOUT_SECONDS, and logged if it fails."""
    try:
        async with asyncio.timeout(RECORD_TIMEOUT_SECONDS):
            await write
    except Exception:
        log.exception("could not record %s in session %s", what, session_id)


async def _sleep_until(moment: datetime) -> None:
    await asyncio.sleep(max((moment - datetime.now(UTC)).total_seconds(), 0.0))


def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is not None and task is not asyncio.current_task():
        task.cancel()


classroom = Classroom()
