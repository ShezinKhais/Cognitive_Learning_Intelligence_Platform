"""Private, session-scoped Graph subscription and restart-safe draft queue."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TranscriptAutomation(Base):
    __tablename__ = "transcript_automation"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("session.session_id", ondelete="CASCADE"), primary_key=True
    )
    meeting_id: Mapped[str] = mapped_column(String(2048))
    organizer_id: Mapped[str] = mapped_column(String(36))
    resource_id: Mapped[str] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scan_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(String(240), default="Waiting for Graph subscription.")


class TranscriptDraftJob(Base):
    __tablename__ = "transcript_draft_job"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcript_automation.session_id", ondelete="CASCADE"), primary_key=True
    )
    transcript_id: Mapped[str] = mapped_column(String(2048), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Only bounded, screened summaries and short evidence quotes; never raw VTT.
    drafts: Mapped[list | None] = mapped_column(JSONB)
