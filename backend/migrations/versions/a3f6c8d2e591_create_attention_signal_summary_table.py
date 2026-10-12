"""create attention signal summary table

Revision ID: a3f6c8d2e591
Revises: d5a2f8c61e47
Create Date: 2026-10-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f6c8d2e591"
down_revision: str | Sequence[str] | None = "d5a2f8c61e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "attention_signal_summary",
        sa.Column("summary_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("gaze_on_screen_ratio", sa.Float(), nullable=True),
        sa.Column("face_present_ratio", sa.Float(), nullable=True),
        sa.Column("speaking_ratio", sa.Float(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "window_seconds > 0", name="ck_attention_signal_summary_window_positive"
        ),
        sa.CheckConstraint("sample_count >= 1", name="ck_attention_signal_summary_sample_count"),
        sa.CheckConstraint(
            "gaze_on_screen_ratio IS NULL OR "
            "(gaze_on_screen_ratio >= 0 AND gaze_on_screen_ratio <= 1)",
            name="ck_attention_signal_summary_gaze_ratio",
        ),
        sa.CheckConstraint(
            "face_present_ratio IS NULL OR (face_present_ratio >= 0 AND face_present_ratio <= 1)",
            name="ck_attention_signal_summary_face_ratio",
        ),
        sa.CheckConstraint(
            "speaking_ratio IS NULL OR (speaking_ratio >= 0 AND speaking_ratio <= 1)",
            name="ck_attention_signal_summary_speaking_ratio",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["student.student_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("summary_id"),
        sa.UniqueConstraint(
            "session_id",
            "student_id",
            "window_start",
            name="uq_attention_signal_summary_window",
        ),
    )
    op.create_index(
        op.f("ix_attention_signal_summary_session_id"),
        "attention_signal_summary",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attention_signal_summary_student_id"),
        "attention_signal_summary",
        ["student_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_attention_signal_summary_student_id"), table_name="attention_signal_summary"
    )
    op.drop_index(
        op.f("ix_attention_signal_summary_session_id"), table_name="attention_signal_summary"
    )
    op.drop_table("attention_signal_summary")
