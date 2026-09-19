"""Engagement record table: stores student engagement measurements.

Extended for Phase 3 (Cyber 1's scoring). status and confidence are written
once at scoring time rather than recomputed from attempt_rate and
attention_signal when the dashboard reads a row: the Phase 1 columns alone
lost which signals actually contributed, and EngagementOut's low-confidence
result must never render as "disengaged" (see its docstring) -- a rule that
has to be applied once, at the point score and confidence were computed
together, not re-derived later from a lossy summary.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EngagementRecord(Base):
    __tablename__ = "engagement_record"

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.session_id"),
        nullable=False,
        index=True,
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student.student_id"),
        nullable=False,
        index=True,
    )

    attempt_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    attention_signal: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    engagement_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # --- Phase 3 additions, mapping onto EngagementOut ---

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="insufficient_data",
        server_default="insufficient_data",
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )

    signals_available: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
        server_default="",
    )
