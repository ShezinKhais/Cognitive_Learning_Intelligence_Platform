"""Deletion request table: a request to erase a session's or a student's data.

Owner: BBIS, Phase 7. A request is made by one admin and decided by another.
target_id is deliberately not a foreign key: the request is the governance
record of what was deleted and who agreed, so it must outlive its target.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DELETION_TARGETS = ("session", "student")
DELETION_STATUSES = ("requested", "approved", "rejected", "executed")


class DeletionRequest(Base):
    __tablename__ = "deletion_request"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('session', 'student')",
            name="ck_deletion_request_target_type",
        ),
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'executed')",
            name="ck_deletion_request_status",
        ),
        Index("ix_deletion_request_target", "target_type", "target_id"),
        # At most one open request per target, however many are filed at once.
        Index(
            "uq_deletion_request_open_target",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'approved')"),
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    target_type: Mapped[str] = mapped_column(String(20), nullable=False)

    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="requested",
        server_default="requested",
        index=True,
    )

    # Why, in a few words. Never personal content.
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=False,
        index=True,
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=True,
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=True,
    )

    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # What the deletion removed, as counts only.
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
