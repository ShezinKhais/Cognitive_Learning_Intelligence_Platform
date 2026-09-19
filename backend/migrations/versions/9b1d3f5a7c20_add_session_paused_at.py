"""add session paused_at

Revision ID: 9b1d3f5a7c20
Revises: 4c2e8a91d7b3
Create Date: 2026-09-19 12:00:00.000000

Records a lecturer's pause in the database, so a restart does not quietly
resume a paused session's question cycle. Null while the session is running.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b1d3f5a7c20"
down_revision: str | Sequence[str] | None = "4c2e8a91d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "session",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("session", "paused_at")
