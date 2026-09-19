"""Delivered question table: one row per checkpoint actually pushed live.

Owner: BBIS, Phase 3. `question` already carries the content and its review
status; this table is the delivery event itself -- when it opened, when and
why it closed, and the respondent counts closing needs to compute once,
because both are used by the dashboard and must not depend on recomputing
them from response rows after the fact.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeliveredQuestion(Base):
    __tablename__ = "delivered_question"

    delivery_id: Mapped[uuid.UUID] = mapped_column(
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

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question.question_id"),
        nullable=False,
        index=True,
    )

    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    window_seconds: Mapped[int] = mapped_column(
        Integer,
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

    respondent_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    eligible_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
