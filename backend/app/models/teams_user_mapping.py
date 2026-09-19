"""Teams user mapping table: one Teams identity linked to one C.L.I.P user.

Owner: BBIS, Phase 4. `teams_user_id` is unique -- a Teams account maps to
exactly one C.L.I.P user, never reassigned silently once linked (see
app.repositories.teams_repository.upsert_mapping for what happens when a
roster sync sees the same Teams id claim a different user: that is a
conflict to report, not a value to overwrite).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeamsUserMapping(Base):
    __tablename__ = "teams_user_mapping"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    teams_user_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id"),
        nullable=False,
        unique=True,
        index=True,
    )

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
