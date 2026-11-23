"""Where the bot can post into a Teams meeting's chat.

Owner: AI 2, Phase 8 (#51). Kept per meeting, apart from its link to a
session, because Teams tells the bot about a meeting whenever the bot hears
from it, which is often before a lecturer links the meeting to a session, and
re-linking a meeting replaces its link row. A reference is taken only from an
activity the Bot Framework authenticator has verified.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.teams_meeting_link import MAX_TEAMS_MEETING_ID_LENGTH


class TeamsMeetingReference(Base):
    __tablename__ = "teams_meeting_reference"

    meeting_id: Mapped[str] = mapped_column(
        String(MAX_TEAMS_MEETING_ID_LENGTH),
        primary_key=True,
    )
    service_url: Mapped[str] = mapped_column(String(512), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(512), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
