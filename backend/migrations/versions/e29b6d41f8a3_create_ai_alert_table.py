"""create ai_alert table

Revision ID: e29b6d41f8a3
Revises: c4f81e2a7b95
Create Date: 2026-10-07 00:00:00.000000

Alerts raised to the lecturer lived only in memory and were lost when the
session ended. This keeps each one with the reason and confidence it was
raised with, the model and prompt behind it when there was one, and the
lecturer's acknowledgement.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e29b6d41f8a3"
down_revision: str | Sequence[str] | None = "c4f81e2a7b95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_alert",
        sa.Column("alert_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=True),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_name", sa.String(length=150), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column(
            "raised_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_by", sa.UUID(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open', 'acknowledged')", name="ck_ai_alert_status"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ai_alert_confidence_range"
        ),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_ai_alert_reason_not_blank"),
        sa.CheckConstraint(
            "(status = 'acknowledged') = (acknowledged_at IS NOT NULL)",
            name="ck_ai_alert_acknowledged_consistent",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["question.question_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["student.student_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["user.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index(op.f("ix_ai_alert_session_id"), "ai_alert", ["session_id"])
    op.create_index(op.f("ix_ai_alert_question_id"), "ai_alert", ["question_id"])
    op.create_index(op.f("ix_ai_alert_student_id"), "ai_alert", ["student_id"])
    op.create_index(op.f("ix_ai_alert_status"), "ai_alert", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_ai_alert_status"), table_name="ai_alert")
    op.drop_index(op.f("ix_ai_alert_student_id"), table_name="ai_alert")
    op.drop_index(op.f("ix_ai_alert_question_id"), table_name="ai_alert")
    op.drop_index(op.f("ix_ai_alert_session_id"), table_name="ai_alert")
    op.drop_table("ai_alert")
