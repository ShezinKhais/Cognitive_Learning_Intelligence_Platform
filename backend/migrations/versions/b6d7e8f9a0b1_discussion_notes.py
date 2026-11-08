"""Persist session discussion minutes with session retention."""

import sqlalchemy as sa
from alembic import op

revision = "b6d7e8f9a0b1"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discussion_note",
        sa.Column("note_id", sa.UUID(), primary_key=True),
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("session.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_discussion_note_session_id", "discussion_note", ["session_id"])


def downgrade() -> None:
    op.drop_table("discussion_note")
