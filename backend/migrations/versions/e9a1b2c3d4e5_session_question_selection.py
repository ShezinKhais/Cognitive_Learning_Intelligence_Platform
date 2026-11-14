"""Opt-in, session-specific checkpoint selection."""

import sqlalchemy as sa
from alembic import op

revision = "e9a1b2c3d4e5"
down_revision = "d8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "session",
        sa.Column(
            "question_selection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    # Question copies remain valid course-bank entries assigned to their session.
    op.drop_column("session", "question_selection_enabled")
