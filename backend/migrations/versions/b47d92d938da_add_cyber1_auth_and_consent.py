"""Add Cyber 1 authentication and consent persistence.

Revision ID: b47d92d938da
Revises: f16a4d356f03
Create Date: 2026-08-21 16:19:20.523471
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b47d92d938da"
down_revision: str | Sequence[str] | None = "f16a4d356f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add authentication fields and granular consent storage."""

    op.add_column(
        "user",
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.add_column(
        "user",
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.create_table(
        "consent",
        sa.Column(
            "consent_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "consent_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "granted",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            ("consent_type IN ('terms', 'engagement_monitoring', 'camera', 'microphone')"),
            name="ck_consent_type",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.user_id"],
        ),
        sa.PrimaryKeyConstraint(
            "consent_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "consent_type",
            name="uq_consent_user_type",
        ),
    )


def downgrade() -> None:
    """Remove Cyber 1 authentication and consent persistence."""

    op.drop_table("consent")

    op.drop_column(
        "user",
        "active",
    )

    op.drop_column(
        "user",
        "password_hash",
    )
