"""Attention signal summaries: one row per student per minute of a live session.

Owner: BBIS, Phase 6. Each row aggregates the derived indicators a student's
device sent in that window. A null ratio means no signal was available (camera
or microphone declined or off), never zero, so a missing signal cannot lower an
engagement score. No raw image, audio, video, transcript, landmark or embedding
is ever stored here.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _unit_interval(column: str) -> str:
    return f"{column} IS NULL OR ({column} >= 0 AND {column} <= 1)"


class AttentionSignalSummary(Base):
    __tablename__ = "attention_signal_summary"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "student_id",
            "window_start",
            name="uq_attention_signal_summary_window",
        ),
        CheckConstraint("window_seconds > 0", name="ck_attention_signal_summary_window_positive"),
        CheckConstraint("sample_count >= 1", name="ck_attention_signal_summary_sample_count"),
        CheckConstraint(
            _unit_interval("gaze_on_screen_ratio"), name="ck_attention_signal_summary_gaze_ratio"
        ),
        CheckConstraint(
            _unit_interval("face_present_ratio"), name="ck_attention_signal_summary_face_ratio"
        ),
        CheckConstraint(
            _unit_interval("speaking_ratio"), name="ck_attention_signal_summary_speaking_ratio"
        ),
    )

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student.student_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gaze_on_screen_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_present_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaking_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
