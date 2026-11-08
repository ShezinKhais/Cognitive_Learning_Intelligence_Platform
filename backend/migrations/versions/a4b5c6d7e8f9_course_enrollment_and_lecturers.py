"""Students on more than one course, and the lecturers of each course.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8

student.course_id allowed one course per student. course_enrollment adds
the others; course_lecturer says who teaches each course. Every lecturer
who has run a session for a course is recorded as teaching it, so nobody
loses access to a course they already teach.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_enrollment",
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student.student_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_course_enrollment_course_id", "course_enrollment", ["course_id"])
    op.create_table(
        "course_lecturer",
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_course_lecturer_user_id", "course_lecturer", ["user_id"])
    op.execute(
        """
        INSERT INTO course_lecturer (course_id, user_id)
        SELECT DISTINCT s.course_id, s.instructor_id
        FROM session s JOIN "user" u ON u.user_id = s.instructor_id
        WHERE u.role = 'lecturer'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_course_lecturer_user_id", table_name="course_lecturer")
    op.drop_table("course_lecturer")
    op.drop_index("ix_course_enrollment_course_id", table_name="course_enrollment")
    op.drop_table("course_enrollment")
