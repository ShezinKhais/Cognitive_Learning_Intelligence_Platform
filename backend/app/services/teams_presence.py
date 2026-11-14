"""Who is in each linked Teams meeting, and ending its class once all have gone.

Owner: General CS, Phase 8.

- The bot hears each join and leave in a meeting whose class is linked. It
  keeps the Teams identities in the call, in memory, for as long as the
  meeting has anyone in it.
- When the last person it saw join leaves, the class is ended after a short
  wait (TEAMS_EMPTY_MEETING_END_SECONDS), so someone dropping out and
  rejoining does not end it. Anyone joining in the wait cancels it.
- Teams' own meeting end usually arrives first and ends the class anyway.
  This covers a meeting whose end is not delivered, and the case where
  everyone has left but the meeting is still open in Teams.
- A process that restarted mid-meeting has not seen the joins before it.
  So the class is left running if anyone is still connected to it in
  C.L.I.P, and a leave from someone it never saw join is ignored.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import ClipError
from app.models.session import Session
from app.realtime.classroom import classroom
from app.schemas.session import SessionStatus
from app.services import session_lifecycle
from app.services.meeting_directory import meetings

log = logging.getLogger("clip.teams.presence")


class MeetingPresence:
    def __init__(self) -> None:
        self.present: dict[str, set[str]] = {}
        self.timers: dict[str, asyncio.Task[None]] = {}

    def joined(self, meeting_id: str, people: Iterable[str]) -> None:
        self.present.setdefault(meeting_id, set()).update(people)
        self._cancel(meeting_id)

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

    def count(self, meeting_id: str) -> int:
        return len(self.present.get(meeting_id, ()))

    def end_when_empty(
        self, meeting_id: str, delay: float, end: Callable[[str], Awaitable[None]]
    ) -> None:
        """Run end(meeting_id) after delay, unless someone joins first."""
        self._cancel(meeting_id)
        if delay <= 0:
            return

        async def wait() -> None:
            await asyncio.sleep(delay)
            if self.timers.get(meeting_id) is task:
                del self.timers[meeting_id]
            if self.present.get(meeting_id):
                return
            await end(meeting_id)

        task = asyncio.create_task(wait(), name=f"teams-empty-{meeting_id[:24]}")
        self.timers[meeting_id] = task

    def forget(self, meeting_id: str) -> None:
        self.present.pop(meeting_id, None)
        self._cancel(meeting_id)

    def _cancel(self, meeting_id: str) -> None:
        timer = self.timers.pop(meeting_id, None)
        if timer is not None and not timer.done():
            timer.cancel()


presence = MeetingPresence()


async def end_empty_class(meeting_id: str) -> None:
    """End the class linked to a meeting everyone has left."""
    settings = get_settings()
    try:
        async with get_session_factory()() as db:
            session_id = await meetings.directory.session_for(meeting_id)
            if session_id is None:
                return
            if classroom.anyone_connected(session_id):
                log.info(
                    "meeting %s is empty in Teams but its class still has people connected; "
                    "left running",
                    meeting_id,
                )
                return
            status = await db.scalar(select(Session.status).where(Session.session_id == session_id))
            if status != SessionStatus.ACTIVE.value:
                return
            owner = await session_lifecycle.meeting_owner(db, meeting_id, settings)
            if owner is None:
                return
            await session_lifecycle.end_session(db, owner, session_id)
            log.info("session %s ended: everyone left meeting %s", session_id, meeting_id)
    except ClipError as exc:
        log.warning("meeting %s emptied but its class was not ended: %s", meeting_id, exc)
    except Exception:
        log.exception("meeting %s emptied but ending its class failed", meeting_id)
