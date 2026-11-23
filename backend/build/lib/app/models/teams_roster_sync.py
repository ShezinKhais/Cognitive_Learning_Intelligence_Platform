"""Microsoft Teams roster synchronization events."""

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
from app.models.teams_meeting_link import MAX_TEAMS_MEETING_ID_LENGTH

MAX_TEAMS_EVENT_ID_LENGTH = 256

ROSTER_EVENT_TYPES = (
    "snapshot",
    "participant_joined",
    "participant_left",
)
ROSTER_SYNC_STATUSES = (
    "received",
    "processed",
    "failed",
)


class TeamsRosterSync(Base):
    """One idempotent roster event received for a Teams meeting."""

    __tablename__ = "teams_roster_sync"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "source_event_id",
            name="uq_teams_roster_sync_meeting_source_event",
        ),
        CheckConstraint(
            "event_type IN ('snapshot', 'participant_joined', 'participant_left')",
            name="ck_teams_roster_sync_event_type",
        ),
        CheckConstraint(
            "status IN ('received', 'processed', 'failed')",
            name="ck_teams_roster_sync_status",
        ),
        CheckConstraint(
            "participant_count >= 0",
            name="ck_teams_roster_sync_participant_count_nonnegative",
        ),
        CheckConstraint(
            "matched_count >= 0",
            name="ck_teams_roster_sync_matched_count_nonnegative",
        ),
        CheckConstraint(
            "unmatched_count >= 0",
            name="ck_teams_roster_sync_unmatched_count_nonnegative",
        ),
        CheckConstraint(
            "missing_count >= 0",
            name="ck_teams_roster_sync_missing_count_nonnegative",
        ),
        CheckConstraint(
            "duplicate_count >= 0",
            name="ck_teams_roster_sync_duplicate_count_nonnegative",
        ),
    )

    sync_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    meeting_id: Mapped[str] = mapped_column(
        String(MAX_TEAMS_MEETING_ID_LENGTH),
        nullable=False,
        index=True,
    )

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.session_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source_event_id: Mapped[str] = mapped_column(
        String(MAX_TEAMS_EVENT_ID_LENGTH),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="received",
        server_default="received",
        index=True,
    )

    participant_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    matched_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    unmatched_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    missing_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    duplicate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
