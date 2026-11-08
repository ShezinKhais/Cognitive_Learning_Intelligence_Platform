"""Lecturers ask for new courses; an admin approves or declines."""

import sqlalchemy as sa
from alembic import op

revision = "f4c5d6e7a8b9"
down_revision = "d8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "course_request",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column(
            "requested_by",
            sa.UUID(),
            sa.ForeignKey("user.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decided_by", sa.UUID(), sa.ForeignKey("user.user_id", ondelete="SET NULL")),
        sa.Column("decision_note", sa.String(500)),
        sa.Column("course_id", sa.UUID(), sa.ForeignKey("course.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined')", name="ck_course_request_status"
        ),
    )
    op.create_index("ix_course_request_requested_by", "course_request", ["requested_by"])
    op.create_index(
        "uq_course_request_pending_code",
        "course_request",
        ["code"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_index("uq_course_request_pending_code", table_name="course_request")
    op.drop_index("ix_course_request_requested_by", table_name="course_request")
    op.drop_table("course_request")
