"""Session table: one class, from preparation through to its end.

start_time and end_time are the timetabled slot. A session created on the day
has no scheduled end, so end_time is optional. ended_at is when the lecturer
actually ended it, which is what SessionOut reports. paused_at is set while
the lecturer has paused a running session and cleared when it resumes, so a
restart does not quietly resume the question cycle.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Session(Base):
    __tablename__ = "session"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    instructor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=False,
        index=True,
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("course.id"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
        server_default="",
    )

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # The lecturer's AI switches for this class, copied from the course when
    # the class is created.
    ai_auto_checkpoints: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    ai_learning_assistant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    ai_refocus_nudges: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    ai_engagement_estimates: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    # Opt-in lesson plan. False preserves the existing course-bank workflow.
    question_selection_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # The lecturer's pacing for this class: minutes between automatic
    # checkpoints and seconds to answer. Empty means the deployment's own.
    checkpoint_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # When the class actually started, which may differ from its timetabled
    # start_time. Attendance measures lateness from the later of the two.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # End the class when its lecturer leaves the linked Teams call.
    end_when_lecturer_leaves: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
