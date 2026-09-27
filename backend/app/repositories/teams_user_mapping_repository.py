"""Persistence and resolution for Microsoft Teams user identities."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teams_user_mapping import TeamsUserMapping

TEAMS_USER_MAPPING_LOCK_ID = 4_348_372_110


class TeamsUserMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_for(
        self,
        *,
        tenant_id: str,
        teams_user_id: str,
    ) -> uuid.UUID | None:
        result = await self.session.execute(
            select(TeamsUserMapping.user_id).where(
                TeamsUserMapping.tenant_id == tenant_id,
                TeamsUserMapping.teams_user_id == teams_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def teams_user_for(
        self,
        *,
        tenant_id: str,
        user_id: uuid.UUID,
    ) -> str | None:
        result = await self.session.execute(
            select(TeamsUserMapping.teams_user_id).where(
                TeamsUserMapping.tenant_id == tenant_id,
                TeamsUserMapping.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def record_unmatched(
        self,
        *,
        tenant_id: str,
        teams_user_id: str,
    ) -> TeamsUserMapping:
        """Remember an unresolved identity without erasing an existing match."""
        statement = (
            insert(TeamsUserMapping)
            .values(
                mapping_id=uuid.uuid4(),
                tenant_id=tenant_id,
                teams_user_id=teams_user_id,
                user_id=None,
            )
            .on_conflict_do_update(
                constraint="uq_teams_user_mapping_tenant_teams_user",
                set_={"updated_at": func.now()},
            )
            .returning(TeamsUserMapping)
        )
        mapping = (await self.session.execute(statement)).scalar_one()
        await self.session.refresh(mapping)
        return mapping

    async def link_user(
        self,
        *,
        tenant_id: str,
        teams_user_id: str,
        user_id: uuid.UUID,
    ) -> TeamsUserMapping:
        """Resolve both sides, replacing conflicting mappings in this tenant."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": TEAMS_USER_MAPPING_LOCK_ID},
        )
        await self.session.execute(
            delete(TeamsUserMapping).where(
                TeamsUserMapping.tenant_id == tenant_id,
                or_(
                    TeamsUserMapping.teams_user_id == teams_user_id,
                    TeamsUserMapping.user_id == user_id,
                ),
            )
        )

        mapping = TeamsUserMapping(
            tenant_id=tenant_id,
            teams_user_id=teams_user_id,
            user_id=user_id,
        )
        self.session.add(mapping)
        await self.session.flush()
        await self.session.refresh(mapping)
        return mapping

    async def list_unmatched(
        self,
        *,
        tenant_id: str,
    ) -> list[TeamsUserMapping]:
        result = await self.session.execute(
            select(TeamsUserMapping)
            .where(
                TeamsUserMapping.tenant_id == tenant_id,
                TeamsUserMapping.user_id.is_(None),
            )
            .order_by(
                TeamsUserMapping.created_at,
                TeamsUserMapping.mapping_id,
            )
        )
        return list(result.scalars().all())
