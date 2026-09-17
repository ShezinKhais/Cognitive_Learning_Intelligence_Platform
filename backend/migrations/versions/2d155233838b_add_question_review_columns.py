"""add question review columns

Revision ID: 2d155233838b
Revises: cd914692a316
Create Date: 2026-08-15 00:00:00.000000

Adds the columns app.schemas.content.QuestionOut requires that the Phase 1
question table didn't have yet: status, difficulty, options, correct_option,
topic, source_slide, source_excerpt, reviewed_by, reviewed_at. See the
docstring in app/models/question.py for why this landed on Cyber 2's branch
rather than BBIS's.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d155233838b"
down_revision: str | Sequence[str] | None = "da20367601a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "question",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
    )
    op.add_column(
        "question",
        sa.Column("difficulty", sa.String(length=10), nullable=False, server_default="medium"),
    )
    op.add_column(
        "question",
        sa.Column("options", sa.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "question",
        sa.Column("correct_option", sa.Integer(), nullable=True),
    )
    op.add_column(
        "question",
        sa.Column("topic", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "question",
        sa.Column("source_slide", sa.Integer(), nullable=True),
    )
    op.add_column(
        "question",
        sa.Column("source_excerpt", sa.Text(), nullable=True),
    )
    op.add_column(
        "question",
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
    )
    op.add_column(
        "question",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_question_reviewed_by_user",
        "question",
        "user",
        ["reviewed_by"],
        ["user_id"],
    )
    op.create_index(op.f("ix_question_status"), "question", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_question_status"), table_name="question")
    op.drop_constraint("fk_question_reviewed_by_user", "question", type_="foreignkey")
    op.drop_column("question", "reviewed_at")
    op.drop_column("question", "reviewed_by")
    op.drop_column("question", "source_excerpt")
    op.drop_column("question", "source_slide")
    op.drop_column("question", "topic")
    op.drop_column("question", "correct_option")
    op.drop_column("question", "options")
    op.drop_column("question", "difficulty")
    op.drop_column("question", "status")
