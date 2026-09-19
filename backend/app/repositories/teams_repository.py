"""Database queries for Teams meeting links, user mappings and roster syncs.

Owner: BBIS, Phase 4.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roster_sync_event import RosterSyncEvent
from app.models.session import Session as SessionModel
from app.models.teams_meeting import TeamsMeeting
from app.models.teams_user_mapping import TeamsUserMapping


class TeamsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_meeting(self, teams_meeting_id: str) -> TeamsMeeting | None:
        result = await self.session.execute(
            select(TeamsMeeting).where(TeamsMeeting.teams_meeting_id == teams_meeting_id)
        )
        return result.scalar_one_or_none()

    async def get_session_for_meeting(self, teams_meeting_id: str) -> SessionModel | None:
        result = await self.session.execute(
            select(SessionModel)
            .join(TeamsMeeting, TeamsMeeting.session_id == SessionModel.session_id)
            .where(TeamsMeeting.teams_meeting_id == teams_meeting_id)
        )
        return result.scalar_one_or_none()

    async def find_unlinked_prepared_session(
        self, *, course_id: uuid.UUID, instructor_id: uuid.UUID
    ) -> SessionModel | None:
        """The lecturer's most recent prepared session for this course that no
        meeting has claimed yet, if they built one ahead of time via the REST
        API (material uploaded, questions approved and staged).

        Without this, a meeting-started event would always create a brand
        new, empty session, and a lecturer who prepared everything in advance
        would find Teams starting a *different* session than the one they
        set up -- the readiness gate would then correctly block a session
        that was never going to have questions, defeating the point of
        preparing ahead of time.
        """
        result = await self.session.execute(
            select(SessionModel)
            .outerjoin(TeamsMeeting, TeamsMeeting.session_id == SessionModel.session_id)
            .where(
                SessionModel.course_id == course_id,
                SessionModel.instructor_id == instructor_id,
                SessionModel.status == "prepared",
                TeamsMeeting.id.is_(None),
            )
            .order_by(SessionModel.start_time.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def link_meeting(
        self, *, session_id: uuid.UUID, teams_meeting_id: str, tenant_id: str
    ) -> TeamsMeeting:
        row = TeamsMeeting(
            session_id=session_id, teams_meeting_id=teams_meeting_id, tenant_id=tenant_id
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def mark_meeting_ended(self, teams_meeting_id: str) -> None:
        meeting = await self.get_meeting(teams_meeting_id)
        if meeting is None:
            return
        meeting.ended_at = datetime.now(UTC)
        self.session.add(meeting)
        await self.session.flush()

    async def get_user_mapping(self, teams_user_id: str) -> TeamsUserMapping | None:
        result = await self.session.execute(
            select(TeamsUserMapping).where(TeamsUserMapping.teams_user_id == teams_user_id)
        )
        return result.scalar_one_or_none()

    async def get_mapping_for_user(self, user_id: uuid.UUID) -> TeamsUserMapping | None:
        result = await self.session.execute(
            select(TeamsUserMapping).where(TeamsUserMapping.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def link_user(
        self, *, teams_user_id: str, user_id: uuid.UUID, display_name: str
    ) -> tuple[TeamsUserMapping, bool]:
        """Create or confirm one Teams identity <-> user mapping.

        Returns (mapping, is_conflict). A conflict is a teams_user_id already
        linked to a *different* user_id -- reported to the caller as a
        duplicate rather than silently repointed, since a Teams account is
        assumed to belong to one person for the life of the enrolment.
        """
        existing = await self.get_user_mapping(teams_user_id)
        if existing is not None:
            if existing.user_id != user_id:
                return existing, True
            return existing, False

        row = TeamsUserMapping(
            teams_user_id=teams_user_id, user_id=user_id, display_name=display_name
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row, False

    async def record_roster_sync(
        self,
        *,
        session_id: uuid.UUID,
        matched: int,
        unmatched: int,
        duplicates: int,
    ) -> RosterSyncEvent:
        row = RosterSyncEvent(
            session_id=session_id,
            matched_count=matched,
            unmatched_count=unmatched,
            duplicate_count=duplicates,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row
