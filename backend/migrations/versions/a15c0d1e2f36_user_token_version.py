"""Add account token version for security reset invalidation."""

import sqlalchemy as sa
from alembic import op

revision = "a15c0d1e2f36"
down_revision = "f4c5d6e7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "token_version")
