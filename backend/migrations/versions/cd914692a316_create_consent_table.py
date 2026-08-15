"""create consent table

Revision ID: cd914692a316
Revises: 86dbf6dff19d
Create Date: 2026-08-15 21:09:52.414380

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cd914692a316"
down_revision: str | Sequence[str] | None = "86dbf6dff19d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "consent",
        sa.Column("consent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("consent_type", sa.String(length=50), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "consent_type IN ('terms', 'engagement_monitoring', 'camera', 'microphone')",
            name="ck_consent_type",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.user_id"],
        ),
        sa.PrimaryKeyConstraint("consent_id"),
        sa.UniqueConstraint(
            "user_id",
            "consent_type",
            name="uq_consent_user_type",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("consent")
