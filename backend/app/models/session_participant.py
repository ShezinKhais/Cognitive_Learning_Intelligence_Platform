"""Session participant table: who joined a live session, and when.

Owner: BBIS, Phase 3. Backs the WebSocket session-membership check (a JWT
alone proves identity, not that its holder belongs to this session) and the
"eligible" respondent count a delivered question closes with -- eligible
means present in the session at the time, not enrolled in the course, since
attendance is never total.

A student can hold more than one connection (a stale reconnect, Teams desktop
and a browser tab at once) without creating duplicate participant rows: the
first join sets joined_at, later ones only clear left_at again if the student
had actually left.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SessionParticipant(Base):
    __tablename__ = "session_participant"

    participant_id: Mapped[uuid.UUID] = mapped_column(
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

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=False,
        index=True,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
