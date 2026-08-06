"""Student table: stores student-specific course and support information."""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Student(Base):
    __tablename__ = "student"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=False,
        unique=True,
        index=True,
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("course.id"),
        nullable=False,
        index=True,
    )

    accessibility_need: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    consent_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    attention_threshold: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    special_consideration_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    enrolled_at: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )