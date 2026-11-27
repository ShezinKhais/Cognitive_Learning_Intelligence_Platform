"""Support interactive questions and invalidation of pending chat writes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f213b8a4d670"
down_revision = "d6f2b8a1c904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("question", sa.Column("interaction", postgresql.JSONB(), nullable=True))
    op.add_column(
        "user",
        sa.Column("chat_history_generation", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    # Older code cannot deliver these question types. Keep any authored items
    # and their responses, and require the operator to migrate them explicitly.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM question WHERE interaction IS NOT NULL)")
    ):
        raise RuntimeError("Archive interactive questions before downgrading this release.")
    op.drop_column("user", "chat_history_generation")
    op.drop_column("question", "interaction")
