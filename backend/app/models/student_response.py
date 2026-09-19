"""Student response table: stores answers submitted by students.

Extended for Phase 3 (AI 1's MCQ scoring, General CS's delivery window).
The Phase 1 `answer` column was a single not-null text field with no room for
"exactly one of selected_option or free_text", which AnswerSubmitPayload
(frozen in app.schemas.events) requires, and no way to tell "not answered yet"
apart from "answered nothing". Nothing had been written to this table before
this phase, so the column is replaced rather than kept alongside its
replacement.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StudentResponse(Base):
    __tablename__ = "student_response"

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

    # Exactly one of these is set, enforced by AnswerSubmitPayload before a
    # response ever reaches persistence.
    selected_option: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    free_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    elapsed_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Null until scored. An MCQ is scored immediately; a free-text answer
    # stays null until Phase 5's classifier runs.
    is_correct: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
