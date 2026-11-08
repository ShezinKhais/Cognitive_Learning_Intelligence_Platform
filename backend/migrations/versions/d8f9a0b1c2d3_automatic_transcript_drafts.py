"""Persistent Graph subscriptions and private transcript draft queue."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d8f9a0b1c2d3"
down_revision = "c7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transcript_automation",
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("session.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("meeting_id", sa.String(2048), nullable=False),
        sa.Column("organizer_id", sa.String(36), nullable=False),
        sa.Column("resource_id", sa.String(2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("subscription_id", sa.String(36), unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.String(240), nullable=False),
    )
    op.create_table(
        "transcript_draft_job",
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("transcript_automation.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("transcript_id", sa.String(2048), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("drafts", postgresql.JSONB()),
    )


def downgrade():
    op.drop_table("transcript_draft_job")
    op.drop_table("transcript_automation")
