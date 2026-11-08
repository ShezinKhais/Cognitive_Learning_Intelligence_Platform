"""Distinguish unreviewed live speech from lecturer-reviewed minutes."""

import sqlalchemy as sa
from alembic import op

revision = "c7e8f9a0b1c2"
down_revision = "b6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "discussion_note",
        sa.Column("origin", sa.String(32), nullable=False, server_default="lecturer"),
    )


def downgrade():
    op.drop_column("discussion_note", "origin")
