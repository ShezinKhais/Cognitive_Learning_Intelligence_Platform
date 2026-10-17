"""One row per student, course and semester: what is kept after the purge.

Sums and counts, not averages, so a later purge adds to a row and an average is
still exact. No foreign keys: this is another database, and a student's rows
are found and erased by student_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.history.database import HistoryBase


class StudentSemesterSummary(HistoryBase):
    __tablename__ = "student_semester_summary"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "course_id", "semester", name="uq_history_student_course_semester"
        ),
    )

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    semester: Mapped[str] = mapped_column(String(16))
    sessions_attended: Mapped[int] = mapped_column(Integer, default=0)
    questions_attempted: Mapped[int] = mapped_column(Integer, default=0)
    questions_correct: Mapped[int] = mapped_column(Integer, default=0)
    engagement_sum: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_count: Mapped[int] = mapped_column(Integer, default=0)
    gaze_sum: Mapped[float] = mapped_column(Float, default=0.0)
    gaze_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ArchivedSession(HistoryBase):
    """A session whose totals are already in the summaries, so a retried purge
    never adds it twice. Holds the id of a session that no longer exists."""

    __tablename__ = "archived_session"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
