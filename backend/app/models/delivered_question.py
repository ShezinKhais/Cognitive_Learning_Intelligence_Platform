"""Questions delivered during live sessions and their response windows."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeliveredQuestion(Base):
    __tablename__ = "delivered_question"
    __table_args__ = (
        CheckConstraint(
            "window_seconds >= 0",
            name="ck_delivered_question_window_seconds_nonnegative",
        ),
        CheckConstraint(
            "eligible_count >= 0",
            name="ck_delivered_question_eligible_count_nonnegative",
        ),
        CheckConstraint(
            "respondent_count >= 0",
            name="ck_delivered_question_respondent_count_nonnegative",
        ),
        CheckConstraint(
            "respondent_count <= eligible_count",
            name="ck_delivered_question_respondents_within_eligible",
        ),
        UniqueConstraint(
            "session_id",
            "question_id",
            name="uq_delivered_question_session_question",
        ),
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(
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
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question.question_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    closes_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    close_reason: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    respondent_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
