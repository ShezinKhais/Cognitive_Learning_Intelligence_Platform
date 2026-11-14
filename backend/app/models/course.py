"""COURSE table: a course that materials and sessions belong to."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Course(Base):
    __tablename__ = "course"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # The AI switches every new class of this course starts with. All on
    # unless a lecturer saves their choice for the course.
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

    # The lecturer's pacing for this class: minutes between automatic
    # checkpoints and seconds to answer. Empty means the deployment's own.
    checkpoint_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
