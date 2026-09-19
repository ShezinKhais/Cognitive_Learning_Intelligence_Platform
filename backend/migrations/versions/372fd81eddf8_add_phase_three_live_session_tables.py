"""add phase three live session tables

Revision ID: 372fd81eddf8
Revises: 2d155233838b
Create Date: 2026-09-19 15:46:02.182429

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "372fd81eddf8"
down_revision: str | Sequence[str] | None = "2d155233838b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "session_participant",
        sa.Column("participant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("participant_id"),
    )
    op.create_index(
        op.f("ix_session_participant_session_id"),
        "session_participant",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_session_participant_user_id"), "session_participant", ["user_id"], unique=False
    )
    op.create_table(
        "delivered_question",
        sa.Column("delivery_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=30), nullable=True),
        sa.Column("respondent_count", sa.Integer(), nullable=True),
        sa.Column("eligible_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["question.question_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"]),
        sa.PrimaryKeyConstraint("delivery_id"),
    )
    op.create_index(
        op.f("ix_delivered_question_question_id"),
        "delivered_question",
        ["question_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_delivered_question_session_id"),
        "delivered_question",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "missed_response",
        sa.Column("missed_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["question.question_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"]),
        sa.ForeignKeyConstraint(["student_id"], ["student.student_id"]),
        sa.PrimaryKeyConstraint("missed_id"),
    )
    op.create_index(
        op.f("ix_missed_response_question_id"), "missed_response", ["question_id"], unique=False
    )
    op.create_index(
        op.f("ix_missed_response_session_id"), "missed_response", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_missed_response_student_id"), "missed_response", ["student_id"], unique=False
    )
    op.add_column(
        "session", sa.Column("title", sa.String(length=255), server_default="", nullable=False)
    )
    op.add_column("session", sa.Column("teams_meeting_id", sa.String(length=255), nullable=True))
    op.add_column("student_response", sa.Column("selected_option", sa.Integer(), nullable=True))
    op.add_column("student_response", sa.Column("free_text", sa.Text(), nullable=True))
    # No existing rows predate this phase, so backfilling with a default is
    # unnecessary, but a server_default keeps this migration safe to run
    # against a database that already has student_response rows from a
    # partial deployment.
    op.add_column(
        "student_response",
        sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False),
    )
    op.alter_column(
        "student_response",
        "is_correct",
        existing_type=sa.BOOLEAN(),
        nullable=True,
    )
    op.drop_column("student_response", "answer")
    op.add_column(
        "engagement_record",
        sa.Column(
            "status", sa.String(length=30), server_default="insufficient_data", nullable=False
        ),
    )
    op.add_column(
        "engagement_record",
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "engagement_record",
        sa.Column("signals_available", sa.String(length=100), server_default="", nullable=False),
    )
    op.alter_column(
        "engagement_record",
        "engagement_score",
        existing_type=sa.Float(),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "engagement_record",
        "engagement_score",
        existing_type=sa.Float(),
        nullable=False,
    )
    op.drop_column("engagement_record", "signals_available")
    op.drop_column("engagement_record", "confidence")
    op.drop_column("engagement_record", "status")
    op.add_column(
        "student_response",
        sa.Column("answer", sa.TEXT(), autoincrement=False, nullable=False, server_default=""),
    )
    op.alter_column(
        "student_response",
        "is_correct",
        existing_type=sa.BOOLEAN(),
        nullable=False,
    )
    op.drop_column("student_response", "elapsed_ms")
    op.drop_column("student_response", "free_text")
    op.drop_column("student_response", "selected_option")
    op.drop_column("session", "teams_meeting_id")
    op.drop_column("session", "title")
    op.drop_index(op.f("ix_missed_response_student_id"), table_name="missed_response")
    op.drop_index(op.f("ix_missed_response_session_id"), table_name="missed_response")
    op.drop_index(op.f("ix_missed_response_question_id"), table_name="missed_response")
    op.drop_table("missed_response")
    op.drop_index(op.f("ix_delivered_question_session_id"), table_name="delivered_question")
    op.drop_index(op.f("ix_delivered_question_question_id"), table_name="delivered_question")
    op.drop_table("delivered_question")
    op.drop_index(op.f("ix_session_participant_user_id"), table_name="session_participant")
    op.drop_index(op.f("ix_session_participant_session_id"), table_name="session_participant")
    op.drop_table("session_participant")
