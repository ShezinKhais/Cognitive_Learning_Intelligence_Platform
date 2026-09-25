"""Which Teams meeting each session is held in.

Owner: General CS, Phase 4, for the contract. BBIS provides the store that
keeps it (meeting IDs and Teams user mappings), and registers it on
meetings.directory at startup.

Until then the directory is kept in this process, which is enough for the
mock adapter in development and loses every link on restart.
check_wiring() says so at startup, and refuses to start in production.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from app.core.config import Settings, get_settings

log = logging.getLogger("clip.meetings")


class MeetingDirectory(Protocol):
    """One meeting is linked to at most one session, and one session to at
    most one meeting. Linking either side again replaces its old link."""

    async def session_for(self, meeting_id: str) -> UUID | None: ...

    async def meeting_for(self, session_id: UUID) -> str | None: ...

    async def link(self, meeting_id: str, session_id: UUID) -> None: ...


class InMemoryMeetingDirectory:
    def __init__(self) -> None:
        self._sessions: dict[str, UUID] = {}
        self._meetings: dict[UUID, str] = {}

    async def session_for(self, meeting_id: str) -> UUID | None:
        return self._sessions.get(meeting_id)

    async def meeting_for(self, session_id: UUID) -> str | None:
        return self._meetings.get(session_id)

    async def link(self, meeting_id: str, session_id: UUID) -> None:
        # Unlink both sides first, so neither keeps pointing at a partner
        # that has moved on.
        old_session = self._sessions.pop(meeting_id, None)
        if old_session is not None:
            self._meetings.pop(old_session, None)
        old_meeting = self._meetings.pop(session_id, None)
        if old_meeting is not None:
            self._sessions.pop(old_meeting, None)
        self._sessions[meeting_id] = session_id
        self._meetings[session_id] = meeting_id


class Meetings:
    """Where the directory is registered. One per process, like the classroom."""

    def __init__(self, settings: Callable[[], Settings] = get_settings) -> None:
        self._settings = settings
        self.directory: MeetingDirectory = InMemoryMeetingDirectory()

    def check_wiring(self) -> None:
        if not isinstance(self.directory, InMemoryMeetingDirectory):
            return
        problem = "no MeetingDirectory is registered, so meeting links are lost on restart"
        if self._settings().is_production:
            raise RuntimeError(f"Refusing to start meetings: {problem}")
        log.warning("%s", problem)


meetings = Meetings()
