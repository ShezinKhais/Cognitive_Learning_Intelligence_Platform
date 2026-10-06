"""add question reference_answer and key_points

Revision ID: a7d3e5c91b42
Revises: 3cc5df760772
Create Date: 2026-10-06 00:00:00.000000

Phase 5 free-text questions carry a model answer and the key points a full
answer must cover. The classifier grades a student's answer against these, so
they have to be stored with the question. Both are nullable: multiple-choice
questions, and every row that exists today, have neither.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7d3e5c91b42"
down_revision: str | Sequence[str] | None = "3cc5df760772"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("question", sa.Column("reference_answer", sa.Text(), nullable=True))
    op.add_column(
        "question",
        sa.Column("key_points", postgresql.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("question", "key_points")
    op.drop_column("question", "reference_answer")
