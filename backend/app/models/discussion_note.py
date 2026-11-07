"""Lecturer-published, course-shareable minutes for one session."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DiscussionNote(Base):
    __tablename__ = "discussion_note"

    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session.session_id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
