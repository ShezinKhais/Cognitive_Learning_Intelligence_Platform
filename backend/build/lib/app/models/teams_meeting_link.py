"""Teams meeting links persisted across application restarts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MAX_TEAMS_MEETING_ID_LENGTH = 256


class TeamsMeetingLink(Base):
    """A one-to-one link between a Teams meeting and a C.L.I.P. session."""

    __tablename__ = "teams_meeting_link"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            name="uq_teams_meeting_link_session_id",
        ),
    )

    meeting_id: Mapped[str] = mapped_column(
        String(MAX_TEAMS_MEETING_ID_LENGTH),
        primary_key=True,
    )

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("session.session_id", ondelete="CASCADE"),
        nullable=False,
    )

    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
