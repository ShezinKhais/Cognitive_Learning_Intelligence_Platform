"""Microsoft Teams identities mapped to C.L.I.P. users."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MAX_TEAMS_TENANT_ID_LENGTH = 256
MAX_TEAMS_USER_ID_LENGTH = 256


class TeamsUserMapping(Base):
    """A validated Microsoft Entra identity mapped to a C.L.I.P. user.

    tenant_id is the server-validated token tid claim, and teams_user_id is
    the server-validated Entra/AAD object ID from the oid claim. Display names,
    email addresses and client-provided TeamsJS identifiers must not be used
    as this mapping key.
    """

    __tablename__ = "teams_user_mapping"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "teams_user_id",
            name="uq_teams_user_mapping_tenant_teams_user",
        ),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_teams_user_mapping_tenant_user",
        ),
    )

    mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    tenant_id: Mapped[str] = mapped_column(
        String(MAX_TEAMS_TENANT_ID_LENGTH),
        nullable=False,
        index=True,
    )

    teams_user_id: Mapped[str] = mapped_column(
        String(MAX_TEAMS_USER_ID_LENGTH),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
