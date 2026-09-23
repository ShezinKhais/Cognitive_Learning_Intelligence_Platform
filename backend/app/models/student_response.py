"""Student answers accepted during live sessions."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StudentResponse(Base):
    __tablename__ = "student_response"
    __table_args__ = (
        CheckConstraint(
            (
                "(selected_option IS NOT NULL AND free_text IS NULL) OR "
                "(selected_option IS NULL AND free_text IS NOT NULL)"
            ),
            name="ck_student_response_exactly_one_answer",
        ),
        CheckConstraint(
            "selected_option IS NULL OR selected_option >= 0",
            name="ck_student_response_selected_option_nonnegative",
        ),
        CheckConstraint(
            "elapsed_ms IS NULL OR elapsed_ms >= 0",
            name="ck_student_response_elapsed_ms_nonnegative",
        ),
        UniqueConstraint(
            "session_id",
            "student_id",
            "question_id",
            name="uq_student_response_session_student_question",
        ),
    )

    response_id: Mapped[uuid.UUID] = mapped_column(
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
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question.question_id"),
        nullable=False,
        index=True,
    )
    selected_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
