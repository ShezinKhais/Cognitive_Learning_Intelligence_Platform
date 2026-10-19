"""A student's request for special consideration in class, and its decision."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConsiderationRequest(Base):
    __tablename__ = "consideration_request"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'withdrawn')",
            name="ck_consideration_request_status",
        ),
        # One request waiting per student.
        Index(
            "uq_consideration_request_one_pending",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student.student_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # What the student asked for, from ConsiderationNeed.
    needs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # The last day it applies; null is until the end of term.
    until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Seen by administrators only, never by the lecturer.
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.user_id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
