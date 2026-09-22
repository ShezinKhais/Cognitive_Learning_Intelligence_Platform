"""add session lifecycle columns

Revision ID: 4c2e8a91d7b3
Revises: 63cc1030dce5
Create Date: 2026-09-19 00:00:00.000000

SessionOut has carried a title and an ended_at since Phase 1, and the session
table had neither. A session created on the day also has no timetabled end,
so end_time becomes optional. Existing rows keep their values; their title is
empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c2e8a91d7b3"
down_revision: str | Sequence[str] | None = "63cc1030dce5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "session",
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "session",
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("session", "end_time", existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # A session with no timetabled end is given its actual end, or failing
    # that its start, so the column can be required again.
    op.execute(
        "UPDATE session SET end_time = COALESCE(ended_at, start_time) WHERE end_time IS NULL"
    )
    op.alter_column("session", "end_time", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_column("session", "ended_at")
    op.drop_column("session", "title")
