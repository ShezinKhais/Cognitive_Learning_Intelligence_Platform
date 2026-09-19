"""What a running session is doing from one second to the next.

Owner: General CS, Phase 3.

The database records what a session is (prepared, active, ended) and which
questions it has delivered. Which question is open now, who has answered it,
when its window shuts and when the next one is due live here, in the process
that holds the session's sockets, and nowhere else.

A restart loses that. The question that was open is abandoned without a
question.closed, since its window has no owner any more, and the cycle
resumes the next time anything touches the session: the lecturer's panel
reconnecting, a student joining, or a manual delivery. See restore().

Scoring and storing an answer belong to AI 1 and BBIS. They plug in through
ResponseRecorder; until one is set, an accepted answer is counted towards the
question's respondents and kept nowhere else.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.errors import ConflictError
from app.models.session import Session
from app.realtime.hub import SessionHub, hub
from app.repositories.session_repository import SessionRepository
from app.schemas.events import (
    AnswerReceiptPayload,
    AnswerSubmitPayload,
    QuestionClosedPayload,
    QuestionCloseReason,
    QuestionDeliveredPayload,
    ServerEventType,
    SessionStatePayload,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus

log = logging.getLogger("clip.classroom")


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

    Raising refuses the answer: the student is told it was not saved and may
    submit again while the window is open.
    """

    async def record(self, submission: Submission) -> None: ...


@dataclass
class _OpenQuestion:
    question_id: UUID
    option_count: int | None
    closes_at: datetime
    delivered: dict
    # Students connected when the question went out. Anyone who answers
    # counts as eligible too, including a student who joined late.
    present: set[UUID]
    answered: set[UUID] = field(default_factory=set)
    closer: asyncio.Task[None] | None = None


class LiveSession:
    def __init__(self, session_id: UUID, delivered: int, interval: timedelta) -> None:
        self.session_id = session_id
        # Every change to the open question happens under this lock, and so do
        # the events announcing it, so question.closed can never overtake the
        # question.delivered it closes.
        self.lock = asyncio.Lock()
        self.open: _OpenQuestion | None = None
        self.delivered = delivered
        self.next_due = datetime.now(UTC) + interval
        self.cycle: asyncio.Task[None] | None = None


class Classroom:
    """Every live session this process is running. One instance per process,
    for the same reason there is one hub."""

    def __init__(
        self,
        events: SessionHub = hub,
        sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory,
        settings: Callable[[], Settings] = get_settings,
    ) -> None:
        self._hub = events
        self._sessions = sessions
        self._settings = settings
        self._live: dict[UUID, LiveSession] = {}
        self.recorder: ResponseRecorder | None = None

    @property
    def _interval(self) -> timedelta:
        return timedelta(seconds=self._settings().checkpoint_interval_seconds)

    @property
    def _window(self) -> timedelta:
        return timedelta(seconds=self._settings().checkpoint_response_window_seconds)

    # -- lifecycle ----------------------------------------------------------

    def get_running(self, session_id: UUID) -> LiveSession | None:
        return self._live.get(session_id)

    def activate(self, session_id: UUID, delivered: int = 0) -> LiveSession:
        """Begin running a session: its cycle starts counting from now."""
        live = self._live.get(session_id)
        if live is None:
            live = self._live[session_id] = LiveSession(session_id, delivered, self._interval)
            live.cycle = asyncio.create_task(
                self._run_cycle(live), name=f"question-cycle-{session_id}"
            )
        return live

    async def restore(self, db: AsyncSession, row: Session) -> LiveSession | None:
        """The running state of an active session, rebuilt after a restart."""
        if row.status != SessionStatus.ACTIVE.value:
            return None
        live = self._live.get(row.session_id)
        if live is None:
            delivered = await SessionRepository(db).count_delivered(row.session_id)
            live = self.activate(row.session_id, delivered)
        return live

    async def end(self, session_id: UUID, status: SessionStatus, delivered: int) -> None:
        """Close the open question, stop the cycle and tell everyone.

        The caller has already recorded the new status. Ending a session this
        process was not running, after a restart, still announces it.
        """
        live = self._live.pop(session_id, None)
        if live is not None:
            async with live.lock:
                await self._close_locked(live, QuestionCloseReason.SESSION_ENDED)
            _cancel(live.cycle)
        await self._hub.broadcast(
            session_id,
            ServerEventType.SESSION_STATE,
            self.state(session_id, status, delivered).model_dump(mode="json"),
        )
        self._hub.forget_session(session_id)

    async def shutdown(self) -> None:
        """Stop every timer this process owns. Sessions stay active in the
        database and resume in whichever process next touches them."""
        tasks = []
        for live in self._live.values():
            tasks.append(live.cycle)
            if live.open is not None:
                tasks.append(live.open.closer)
        self._live.clear()
        for task in tasks:
            _cancel(task)
        for task in tasks:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    # -- what a client sees -------------------------------------------------

    def state(
        self, session_id: UUID, status: SessionStatus, delivered: int = 0
    ) -> SessionStatePayload:
        live = self._live.get(session_id)
        return SessionStatePayload(
            session_id=session_id,
            status=status,
            participant_count=self._hub.participant_count(session_id),
            active_question_id=live.open.question_id if live and live.open else None,
            questions_delivered=live.delivered if live else delivered,
        )

    def welcome(
        self, session_id: UUID, recorded: SessionStatus, user_id: UUID, role: Role | None
    ) -> list[tuple[ServerEventType, dict]]:
        """What a joining connection is told: the session's state and, for a
        student who has not answered it yet, the question that is open.

        recorded is the status read when the socket was admitted. The session
        may have started or ended since, and the event announcing it went out
        before this connection joined, so what is running here now wins.

        A student reconnecting mid-question may also receive that question in
        the replay. Clients treat a second question.delivered with the same
        question_id as the same question.
        """
        if session_id in self._live:
            status = SessionStatus.ACTIVE
        elif recorded is SessionStatus.ACTIVE:
            status = SessionStatus.ENDED
        else:
            status = recorded
        state = self.state(session_id, status).model_dump(mode="json")
        events = [(ServerEventType.SESSION_STATE, state)]
        live = self._live.get(session_id)
        open_ = live.open if live else None
        if (
            open_ is not None
            and role is Role.STUDENT
            and user_id not in open_.answered
            and datetime.now(UTC) < open_.closes_at
        ):
            events.append((ServerEventType.QUESTION_DELIVERED, open_.delivered))
        return events

    # -- delivery -----------------------------------------------------------

    async def deliver(
        self, db: AsyncSession, row: Session, question_id: UUID | None = None
    ) -> QuestionDeliveredPayload | None:
        """Deliver the named question, or the next staged one, to the session.

        The lecturer's manual trigger and the cycle both come through here.
        The caller holds the session row locked and has checked it is active.
        Returns None when there is nothing staged to deliver. Raises
        ConflictError while another question is still open.
        """
        live = await self.restore(db, row)
        if live is None:
            raise ConflictError("The session is not running.", {"status": row.status})

        async with live.lock:
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
            payload = QuestionDeliveredPayload(
                question_id=question.question_id,
                prompt=question.question_text,
                options=question.options,
                closes_at=now + window,
                window_seconds=int(window.total_seconds()),
                source_slide=question.source_slide,
            )
            # Recorded before anyone is told, so a delivered question is
            # never missing from the session's history.
            await db.commit()

            live.open = _OpenQuestion(
                question_id=question.question_id,
                option_count=len(question.options) if question.options else None,
                closes_at=payload.closes_at,
                delivered=payload.model_dump(mode="json"),
                present=self._hub.student_ids(row.session_id),
            )
            live.delivered += 1
            # A manual question restarts the wait, so the cycle never sends
            # another one moments after the lecturer did.
            live.next_due = now + self._interval
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
        async with live.lock:
            if live.open is open_:
                await self._close_locked(live, QuestionCloseReason.WINDOW_ELAPSED)

    async def _close_locked(self, live: LiveSession, reason: QuestionCloseReason) -> None:
        open_ = live.open
        if open_ is None:
            return
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

    async def _run_cycle(self, live: LiveSession) -> None:
        """Deliver the next staged question every checkpoint interval."""
        while True:
            wait = (live.next_due - datetime.now(UTC)).total_seconds()
            if wait > 0:
                # Woken early or late by a manual delivery moving next_due,
                # the loop simply measures again.
                await asyncio.sleep(wait)
                continue
            live.next_due = datetime.now(UTC) + self._interval
            try:
                if not await self._deliver_on_schedule(live.session_id):
                    # Ended by a call that found nothing running here, such as
                    # an end racing a start. Nothing else will remove it.
                    if self._live.get(live.session_id) is live:
                        del self._live[live.session_id]
                    return
            except ConflictError:
                pass  # The last question is still open; try at the next interval.
            except Exception:
                log.exception("scheduled delivery failed for session %s", live.session_id)

    async def _deliver_on_schedule(self, session_id: UUID) -> bool:
        """One scheduled delivery. False once the session is no longer active.

        The row stays locked until deliver() commits, so an end arriving
        meanwhile waits for the delivery and then closes the question.
        """
        async with self._sessions()() as db:
            row = await SessionRepository(db).get(session_id, for_update=True)
            if row is None or row.status != SessionStatus.ACTIVE.value:
                return False
            await self.deliver(db, row)
            await db.commit()
        return True

    # -- answers ------------------------------------------------------------

    async def submit(
        self,
        session_id: UUID,
        user_id: UUID,
        role: Role | None,
        answer: AnswerSubmitPayload,
    ) -> AnswerReceiptPayload:
        """Accept or refuse one answer. Every outcome is a receipt, never an
        exception, so the student always hears back."""
        received_at = datetime.now(UTC)

        def refused(reason: str) -> AnswerReceiptPayload:
            return AnswerReceiptPayload(
                question_id=answer.question_id,
                accepted=False,
                received_at=received_at,
                reason=reason,
            )

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

        if self.recorder is not None:
            try:
                await self.recorder.record(
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
                return refused("Your answer could not be saved. Please submit it again.")

        return AnswerReceiptPayload(
            question_id=answer.question_id, accepted=True, received_at=received_at
        )


def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is not None and task is not asyncio.current_task():
        task.cancel()


classroom = Classroom()
