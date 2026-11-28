"""Create private student chatbot exchange storage.

Revision ID: b28e1f7a9c32
Revises: f4c5d6e7a8b9
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "b28e1f7a9c32"
down_revision = "f4c5d6e7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_chat_exchange",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("session.session_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("citations", JSONB(), nullable=False),
        sa.Column("follow_ups", JSONB(), nullable=False),
        sa.Column("general", sa.Boolean(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "student_id",
            "request_id",
            name="uq_student_chat_exchange_student_request",
        ),
    )
    op.create_index(
        "ix_student_chat_exchange_student_id",
        "student_chat_exchange",
        ["student_id"],
    )
    op.create_index(
        "ix_student_chat_exchange_session_id",
        "student_chat_exchange",
        ["session_id"],
    )
    op.create_index(
        "ix_student_chat_exchange_student_created",
        "student_chat_exchange",
        ["student_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_student_chat_exchange_student_created",
        table_name="student_chat_exchange",
    )
    op.drop_index(
        "ix_student_chat_exchange_session_id",
        table_name="student_chat_exchange",
    )
    op.drop_index(
        "ix_student_chat_exchange_student_id",
        table_name="student_chat_exchange",
    )
    op.drop_table("student_chat_exchange")
