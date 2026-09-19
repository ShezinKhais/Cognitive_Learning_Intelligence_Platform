"""Question table: stores questions generated from source materials.

Extended for Phase 2 (Cyber 2's review interface + AI 1's generation). The
Phase 1 version of this table only had question_id/source_material_id/
question_text/session_id/question_type/created_at -- enough to prove the FK
relationships, not enough to back the QuestionOut contract frozen in
app.schemas.content (status, difficulty, options, correct_option, topic,
source_slide, source_excerpt were all missing).

NOTE for BBIS: persistence is your ownership per content.py's docstring.
This extension exists because Cyber 2's review routes cannot function
without it -- nothing here changes the Phase 1 columns or their meaning,
it only adds what QuestionOut already requires. Flag if this should be
restructured differently; happy to adjust once compared with any schema
you were separately planning.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Question(Base):
    __tablename__ = "question"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    source_material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_material.id"),
        nullable=False,
        index=True,
    )

    question_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Set when the question is staged for a class. Generation happens at
    # upload, before any session exists, so a draft has none, and review
    # access follows the material's uploader rather than a session.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.session_id"),
        nullable=True,
        index=True,
    )

    question_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # --- Phase 2 additions, mapping onto QuestionOut ---

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )

    difficulty: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="medium",
        server_default="medium",
    )

    options: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
    )

    correct_option: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    topic: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    source_slide: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    source_excerpt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
