"""When a class actually started, and whether it ends when its lecturer leaves the Teams call."""

import sqlalchemy as sa
from alembic import op

revision = "b4e7d2a9c1f3"
down_revision = "cc4cff64052f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("session", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "session",
        sa.Column(
            "end_when_lecturer_leaves",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("session", "end_when_lecturer_leaves")
    op.drop_column("session", "started_at")
