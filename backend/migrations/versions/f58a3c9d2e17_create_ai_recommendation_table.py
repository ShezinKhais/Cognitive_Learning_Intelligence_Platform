"""create ai_recommendation table

Revision ID: f58a3c9d2e17
Revises: e29b6d41f8a3
Create Date: 2026-10-07 00:00:00.000000

Recommendations shown to the lecturer are kept with the reason and
confidence they were made with, the slides they cite, whether the safe
fallback text was used instead of a model answer, the model and prompt
behind them, and the lecturer's acknowledgement.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f58a3c9d2e17"
down_revision: str | Sequence[str] | None = "e29b6d41f8a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_recommendation",
        sa.Column("recommendation_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("alert_id", sa.UUID(), nullable=True),
        sa.Column("question_id", sa.UUID(), nullable=True),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("used_fallback", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("model_name", sa.String(length=150), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_by", sa.UUID(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged')", name="ck_ai_recommendation_status"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_recommendation_confidence_range",
        ),
        sa.CheckConstraint(
            "length(btrim(recommendation)) > 0", name="ck_ai_recommendation_text_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_ai_recommendation_reason_not_blank"
        ),
        sa.CheckConstraint(
            "(status = 'acknowledged') = (acknowledged_at IS NOT NULL)",
            name="ck_ai_recommendation_acknowledged_consistent",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["ai_alert.alert_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["question_id"], ["question.question_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["student.student_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["user.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("recommendation_id"),
    )
    op.create_index(op.f("ix_ai_recommendation_session_id"), "ai_recommendation", ["session_id"])
    op.create_index(op.f("ix_ai_recommendation_alert_id"), "ai_recommendation", ["alert_id"])
    op.create_index(op.f("ix_ai_recommendation_question_id"), "ai_recommendation", ["question_id"])
    op.create_index(op.f("ix_ai_recommendation_student_id"), "ai_recommendation", ["student_id"])
    op.create_index(op.f("ix_ai_recommendation_status"), "ai_recommendation", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_ai_recommendation_status"), table_name="ai_recommendation")
    op.drop_index(op.f("ix_ai_recommendation_student_id"), table_name="ai_recommendation")
    op.drop_index(op.f("ix_ai_recommendation_question_id"), table_name="ai_recommendation")
    op.drop_index(op.f("ix_ai_recommendation_alert_id"), table_name="ai_recommendation")
    op.drop_index(op.f("ix_ai_recommendation_session_id"), table_name="ai_recommendation")
    op.drop_table("ai_recommendation")
