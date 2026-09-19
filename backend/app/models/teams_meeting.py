"""Teams meeting table: links one Teams online meeting to one C.L.I.P session.

Owner: BBIS, Phase 4. One row per meeting; `teams_meeting_id` is unique so a
duplicate meeting-started webhook delivery (a normal occurrence for webhooks)
is detected as "already linked" rather than creating a second session.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeamsMeeting(Base):
    __tablename__ = "teams_meeting"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    teams_meeting_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session.session_id"),
        nullable=False,
        unique=True,
        index=True,
    )

    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
