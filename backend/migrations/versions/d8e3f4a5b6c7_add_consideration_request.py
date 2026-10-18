"""A student's request for special consideration, decided by an administrator.

Revision ID: d8e3f4a5b6c7
Revises: a8d2f4c61b73

Until now an accommodation could only be set by editing the student row. The
request records what was asked, for how long, and who decided, so approving
one can set the accommodation the live class already honours.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d8e3f4a5b6c7"
down_revision = "a8d2f4c61b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consideration_request",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student.student_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("needs", postgresql.JSONB(), nullable=False),
        sa.Column("until", sa.Date(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.user_id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(300), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'withdrawn')",
            name="ck_consideration_request_status",
        ),
    )
    op.create_index("ix_consideration_request_student_id", "consideration_request", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_consideration_request_student_id", table_name="consideration_request")
    op.drop_table("consideration_request")
