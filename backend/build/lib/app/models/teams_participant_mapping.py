"""Participant outcomes from Microsoft Teams roster synchronization."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.teams_user_mapping import (
    MAX_TEAMS_TENANT_ID_LENGTH,
    MAX_TEAMS_USER_ID_LENGTH,
)

PARTICIPANT_MATCH_STATUSES = (
    "matched",
    "unmatched",
    "missing",
    "duplicate",
)


class TeamsParticipantMapping(Base):
    """How one source roster record mapped into C.L.I.P."""

    __tablename__ = "teams_participant_mapping"
    __table_args__ = (
        UniqueConstraint(
            "sync_id",
            "record_index",
            name="uq_teams_participant_mapping_sync_record",
        ),
        CheckConstraint(
            "record_index >= 0",
            name="ck_teams_participant_mapping_record_index_nonnegative",
        ),
        CheckConstraint(
            "match_status IN ('matched', 'unmatched', 'missing', 'duplicate')",
            name="ck_teams_participant_mapping_match_status",
        ),
    )

    participant_mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    sync_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams_roster_sync.sync_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    record_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    tenant_id: Mapped[str | None] = mapped_column(
        String(MAX_TEAMS_TENANT_ID_LENGTH),
        nullable=True,
        index=True,
    )

    teams_user_id: Mapped[str | None] = mapped_column(
        String(MAX_TEAMS_USER_ID_LENGTH),
        nullable=True,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    match_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
