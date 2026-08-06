"""Breakout room table: stores participation measurements for breakout rooms."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BreakoutRoom(Base):
    __tablename__ = "breakout_room"

    room_id: Mapped[uuid.UUID] = mapped_column(
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

    silence_duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    participation_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )