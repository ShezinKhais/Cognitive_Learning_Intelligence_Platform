"""The lecturer's AI switches, per class and as a course's defaults."""

import sqlalchemy as sa
from alembic import op

revision = "e2b3c4d5f6a7"
down_revision = "d8f9a0b1c2d3"
branch_labels = None
depends_on = None

SWITCHES = (
    "ai_auto_checkpoints",
    "ai_learning_assistant",
    "ai_refocus_nudges",
    "ai_engagement_estimates",
)


def upgrade():
    for table in ("session", "course"):
        for name in SWITCHES:
            op.add_column(
                table,
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()),
            )


def downgrade():
    for table in ("course", "session"):
        for name in reversed(SWITCHES):
            op.drop_column(table, name)
