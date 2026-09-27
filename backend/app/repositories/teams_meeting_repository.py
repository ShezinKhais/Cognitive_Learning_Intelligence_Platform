"""Persistent Microsoft Teams meeting links owned by BBIS."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_session_factory
from app.models.teams_meeting_link import TeamsMeetingLink

# Relinking changes both sides of a one-to-one mapping. Serializing these short
# transactions prevents concurrent requests from leaving conflicting links.
MEETING_LINK_LOCK_ID = 4_348_372_109


class DatabaseMeetingDirectory:
    """Database-backed implementation of General CS's MeetingDirectory contract."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def session_for(self, meeting_id: str) -> UUID | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TeamsMeetingLink.session_id).where(TeamsMeetingLink.meeting_id == meeting_id)
            )
            return result.scalar_one_or_none()

    async def meeting_for(self, session_id: UUID) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TeamsMeetingLink.meeting_id).where(TeamsMeetingLink.session_id == session_id)
            )
            return result.scalar_one_or_none()

    async def link(self, meeting_id: str, session_id: UUID) -> None:
        """Link both sides, replacing either side's previous association."""
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": MEETING_LINK_LOCK_ID},
                )
                await session.execute(
                    delete(TeamsMeetingLink).where(
                        or_(
                            TeamsMeetingLink.meeting_id == meeting_id,
                            TeamsMeetingLink.session_id == session_id,
                        )
                    )
                )
                session.add(
                    TeamsMeetingLink(
                        meeting_id=meeting_id,
                        session_id=session_id,
                    )
                )
