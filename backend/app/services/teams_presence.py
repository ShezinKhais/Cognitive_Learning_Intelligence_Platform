"""Who is in each linked Teams meeting, and ending its class when they go.

Owner: General CS, Phase 8.

- The bot hears each join and leave in a meeting whose class is linked. It
  keeps the Teams identities in the call, in memory, for as long as the
  meeting has anyone in it.
- When the last person it saw join leaves, the class ends after a short wait
  (TEAMS_EMPTY_MEETING_END_SECONDS), so someone dropping out and rejoining
  does not end it. Anyone joining in the wait cancels it.
- A lecturer can choose to have the class end when they leave the call
  (end_when_lecturer_leaves). The same wait applies, and only the lecturer
  rejoining cancels it.
- Either way the lecturer is warned (session.ending, and a Teams pop-up) and
  can keep the class running instead.
- Teams' own meeting end usually arrives first when everyone leaves and ends
  the class anyway. This covers a meeting whose end is not delivered, and the
  case where everyone has left but the meeting is still open in Teams.
- A process that restarted mid-meeting has not seen the joins before it. So
  an emptied call leaves the class running if anyone still has it open in
  C.L.I.P, and a leave from someone it never saw join is ignored.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import ClipError, NotFoundError
from app.models.session import Session
from app.realtime.classroom import classroom
from app.repositories.session_repository import SessionRepository
from app.schemas.session import SessionOut, SessionStatus
from app.services import session_lifecycle
from app.services.meeting_directory import meetings

log = logging.getLogger("clip.teams.presence")

EVERYONE_LEFT = "everyone_left"
LECTURER_LEFT = "lecturer_left"


@dataclass
class Wait:
    session_id: UUID
    reason: str
    ends_at: datetime
    # Who rejoining cancels the wait; None means anyone.
    waiting_for: frozenset[str] | None
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class MeetingPresence:
    def __init__(self) -> None:
        self.present: dict[str, set[str]] = {}
        self.waits: dict[str, Wait] = {}

    def joined(self, meeting_id: str, people: Iterable[str]) -> Wait | None:
        """Put people in the call. Returns the wait their joining cancelled."""
        people = set(people)
        self.present.setdefault(meeting_id, set()).update(people)
        wait = self.waits.get(meeting_id)
        if wait is not None and (wait.waiting_for is None or wait.waiting_for & people):
            return self.cancel(meeting_id)
        return None

    def left(self, meeting_id: str, people: Iterable[str]) -> bool:
        """Take people out of the call. True when that leaves it empty."""
        here = self.present.get(meeting_id)
        if not here:
            return False
        here.difference_update(people)
        if here:
            return False
        del self.present[meeting_id]
        return True

    def in_call(self, meeting_id: str, person: str) -> bool:
        return person in self.present.get(meeting_id, ())

    def count(self, meeting_id: str) -> int:
        return len(self.present.get(meeting_id, ()))

    def end_after(
        self,
        meeting_id: str,
        session_id: UUID,
        reason: str,
        delay: float,
        end: Callable[[str, str], Awaitable[None]],
        waiting_for: Iterable[str] | None = None,
    ) -> Wait | None:
        """Run end(meeting_id, reason) after delay, unless the wait is
        cancelled first. Replaces any wait already running."""
        self.cancel(meeting_id)
        if delay <= 0:
            return None
        wait = Wait(
            session_id,
            reason,
            datetime.now(UTC) + timedelta(seconds=delay),
            frozenset(waiting_for) if waiting_for is not None else None,
        )

        async def run() -> None:
            await asyncio.sleep(delay)
            if self.waits.get(meeting_id) is not wait:
                return
            del self.waits[meeting_id]
            await end(meeting_id, reason)

        wait.task = asyncio.create_task(run(), name=f"teams-end-{meeting_id[:24]}")
        self.waits[meeting_id] = wait
        return wait

    def cancel(self, meeting_id: str) -> Wait | None:
        wait = self.waits.pop(meeting_id, None)
        if wait is not None and wait.task is not None and not wait.task.done():
            wait.task.cancel()
        return wait

    def forget(self, meeting_id: str) -> None:
        self.present.pop(meeting_id, None)
        self.cancel(meeting_id)


presence = MeetingPresence()


async def end_class(meeting_id: str, reason: str) -> None:
    """End the class linked to a meeting its people have left."""
    settings = get_settings()
    try:
        async with get_session_factory()() as db:
            session_id = await meetings.directory.session_for(meeting_id)
            if session_id is None:
                return
            if reason == EVERYONE_LEFT and classroom.anyone_connected(session_id):
                log.info(
                    "meeting %s is empty in Teams but its class still has people connected; "
                    "left running",
                    meeting_id,
                )
                await classroom.tell_ending(session_id, None, None)
                return
            status = await db.scalar(select(Session.status).where(Session.session_id == session_id))
            if status != SessionStatus.ACTIVE.value:
                return
            owner = await session_lifecycle.meeting_owner(db, meeting_id, settings)
            if owner is None:
                return
            await session_lifecycle.end_session(db, owner, session_id)
            log.info("session %s ended: %s meeting %s", session_id, reason, meeting_id)
    except ClipError as exc:
        log.warning("meeting %s: its class was not ended (%s): %s", meeting_id, reason, exc)
    except Exception:
        log.exception("meeting %s: ending its class failed (%s)", meeting_id, reason)


# -- what the lecturer can do about it -------------------------------------------


async def _owned(db: AsyncSession, principal: Principal, session_id: UUID) -> Session:
    return await session_lifecycle.owned_session(SessionRepository(db), principal, session_id)


async def keep_running(db: AsyncSession, principal: Principal, session_id: UUID) -> SessionOut:
    """The lecturer wants the class to carry on: drop the wait to end it."""
    row = await _owned(db, principal, session_id)
    meeting_id = (await meetings.directory.meetings_for([session_id])).get(session_id)
    wait = presence.waits.get(meeting_id) if meeting_id else None
    if wait is None or wait.session_id != session_id:
        raise NotFoundError("The class is not about to end.", {"session_id": str(session_id)})
    presence.cancel(meeting_id)
    log.info("session %s kept running by %s", session_id, principal.user_id)
    await classroom.tell_ending(session_id, None, None)
    return await session_lifecycle.session_out(db, row)


async def set_end_when_lecturer_leaves(
    db: AsyncSession, principal: Principal, session_id: UUID, on: bool
) -> SessionOut:
    row = await _owned(db, principal, session_id)
    row.end_when_lecturer_leaves = on
    await db.commit()
    if not on:
        meeting_id = (await meetings.directory.meetings_for([session_id])).get(session_id)
        wait = presence.waits.get(meeting_id) if meeting_id else None
        if wait is not None and wait.reason == LECTURER_LEFT:
            presence.cancel(meeting_id)
            await classroom.tell_ending(session_id, None, None)
    return await session_lifecycle.session_out(db, row)
