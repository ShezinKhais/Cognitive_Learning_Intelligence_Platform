"""allow one open deletion request per target

Revision ID: a8d2f4c61b73
Revises: f1a7c3d95e20
Create Date: 2026-10-18 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8d2f4c61b73"
down_revision: str | Sequence[str] | None = "f1a7c3d95e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Fails if a target already has two open requests."""
    op.create_index(
        "uq_deletion_request_open_target",
        "deletion_request",
        ["target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'approved')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_deletion_request_open_target", table_name="deletion_request")
