"""stop recording ip addresses in the audit log

Revision ID: f1a7c3d95e20
Revises: e7c2a4f95b18
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a7c3d95e20"
down_revision: str | Sequence[str] | None = "e7c2a4f95b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. The addresses already stored are dropped with the column."""
    op.drop_column("audit_log", "ip_address")


def downgrade() -> None:
    """Downgrade schema. The column returns empty: dropped addresses are not recoverable."""
    op.add_column("audit_log", sa.Column("ip_address", sa.String(length=45), nullable=True))
