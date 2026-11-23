"""Database queries for granular user consent."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import Consent
from app.schemas.identity import ConsentType


class ConsentRepository:
    """Persist and read each user's latest consent decisions."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self.session = session

    async def record(
        self,
        user_id: UUID,
        consent_type: ConsentType,
        granted: bool,
    ) -> Consent:
        """Create or replace the latest decision for one consent type."""

        result = await self.session.execute(
            select(Consent).where(
                Consent.user_id == user_id,
                Consent.consent_type == consent_type.value,
            )
        )

        record = result.scalar_one_or_none()
        timestamp = datetime.now(UTC)

        if record is None:
            record = Consent(
                user_id=user_id,
                consent_type=consent_type.value,
                granted=granted,
                recorded_at=timestamp,
            )

            self.session.add(record)
        else:
            record.granted = granted
            record.recorded_at = timestamp

        await self.session.flush()

        return record

    async def granted_for(
        self,
        user_id: UUID,
    ) -> set[ConsentType]:
        """Return only consent types that are currently granted."""

        result = await self.session.execute(
            select(Consent.consent_type).where(
                Consent.user_id == user_id,
                Consent.granted.is_(True),
            )
        )

        return {ConsentType(consent_type) for consent_type in result.scalars()}
