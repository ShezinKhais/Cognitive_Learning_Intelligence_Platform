"""Persistence and matching for Microsoft Teams roster events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teams_participant_mapping import TeamsParticipantMapping
from app.models.teams_roster_sync import TeamsRosterSync
from app.repositories.teams_user_mapping_repository import (
    TeamsUserMappingRepository,
)

TEAMS_ROSTER_SYNC_LOCK_ID = 4_348_372_111


@dataclass(frozen=True)
class RosterParticipantInput:
    tenant_id: str | None
    teams_user_id: str | None
    display_name: str | None = None


class TeamsRosterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_sync(
        self,
        *,
        meeting_id: str,
        session_id: uuid.UUID | None,
        source_event_id: str,
        event_type: str,
        participants: list[RosterParticipantInput],
    ) -> TeamsRosterSync:
        """Persist one roster event and classify every source record.

        Repeated meeting/source-event pairs return the original event without
        creating duplicate participant records.
        """
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": TEAMS_ROSTER_SYNC_LOCK_ID},
        )

        existing = (
            await self.session.execute(
                select(TeamsRosterSync).where(
                    TeamsRosterSync.meeting_id == meeting_id,
                    TeamsRosterSync.source_event_id == source_event_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        sync = TeamsRosterSync(
            meeting_id=meeting_id,
            session_id=session_id,
            source_event_id=source_event_id,
            event_type=event_type,
            status="received",
            participant_count=len(participants),
        )
        self.session.add(sync)
        await self.session.flush()

        identity_repository = TeamsUserMappingRepository(self.session)
        seen_identities: set[tuple[str, str]] = set()
        participant_rows: list[TeamsParticipantMapping] = []
        counts = {
            "matched": 0,
            "unmatched": 0,
            "missing": 0,
            "duplicate": 0,
        }

        for record_index, participant in enumerate(participants):
            user_id: uuid.UUID | None = None
            reason: str | None = None

            if not participant.tenant_id or not participant.teams_user_id:
                match_status = "missing"
                reason = "Teams tenant or user identifier is missing."
            else:
                identity = (
                    participant.tenant_id,
                    participant.teams_user_id,
                )
                if identity in seen_identities:
                    match_status = "duplicate"
                    reason = "Teams identity is duplicated in this roster event."
                else:
                    seen_identities.add(identity)
                    user_id = await identity_repository.user_for(
                        tenant_id=participant.tenant_id,
                        teams_user_id=participant.teams_user_id,
                    )
                    if user_id is None:
                        match_status = "unmatched"
                        reason = "Teams identity is not mapped to a C.L.I.P. user."
                        await identity_repository.record_unmatched(
                            tenant_id=participant.tenant_id,
                            teams_user_id=participant.teams_user_id,
                        )
                    else:
                        match_status = "matched"

            counts[match_status] += 1
            participant_rows.append(
                TeamsParticipantMapping(
                    sync_id=sync.sync_id,
                    record_index=record_index,
                    tenant_id=participant.tenant_id,
                    teams_user_id=participant.teams_user_id,
                    display_name=participant.display_name,
                    user_id=user_id,
                    match_status=match_status,
                    reason=reason,
                )
            )

        self.session.add_all(participant_rows)
        sync.status = "processed"
        sync.matched_count = counts["matched"]
        sync.unmatched_count = counts["unmatched"]
        sync.missing_count = counts["missing"]
        sync.duplicate_count = counts["duplicate"]
        sync.processed_at = datetime.now(UTC)

        await self.session.flush()
        await self.session.refresh(sync)
        return sync

    async def list_participants(
        self,
        sync_id: uuid.UUID,
    ) -> list[TeamsParticipantMapping]:
        result = await self.session.execute(
            select(TeamsParticipantMapping)
            .where(TeamsParticipantMapping.sync_id == sync_id)
            .order_by(TeamsParticipantMapping.record_index)
        )
        return list(result.scalars().all())
