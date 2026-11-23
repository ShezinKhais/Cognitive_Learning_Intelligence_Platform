"""Consent table: stores each user's latest decision for every consent type."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Consent(Base):
    __tablename__ = "consent"
    __table_args__ = (
        CheckConstraint(
            "consent_type IN ('terms', 'engagement_monitoring', 'camera', 'microphone')",
            name="ck_consent_type",
        ),
        UniqueConstraint(
            "user_id",
            "consent_type",
            name="uq_consent_user_type",
        ),
    )

    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=False,
    )

    consent_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    granted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
