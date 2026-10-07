"""Comprehension result table: stores AI evaluations of student responses."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComprehensionResult(Base):
    __tablename__ = "comprehension_result"

    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_response.response_id"),
        nullable=False,
        # One label per answer: a retried or concurrent write keeps the first.
        unique=True,
        index=True,
    )

    label: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    ai_feedback_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    # --- Phase 5: what produced the result, and why ---

    # The model and prompt that marked this answer, so results can be
    # compared and traced across versions. Null when no model was asked.
    model_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    prompt_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # Plain-language reasons for the label, shown to the lecturer.
    reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    # One verdict per key point, in order: covered, partly or missed.
    key_point_coverage: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    wrong_claim: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Cosine similarity to the reference answer, when it could be measured.
    similarity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
