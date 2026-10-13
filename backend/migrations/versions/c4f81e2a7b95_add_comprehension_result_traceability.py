"""add comprehension_result traceability columns

Revision ID: c4f81e2a7b95
Revises: a7d3e5c91b42
Create Date: 2026-10-07 00:00:00.000000

Phase 5 stores which model and prompt marked an answer, and why. Without
them a stored label cannot be compared across model and prompt versions or
explained to the lecturer. model_name and prompt_version are null for rows
written before this change, and for answers no model was asked about.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4f81e2a7b95"
down_revision: str | Sequence[str] | None = "a7d3e5c91b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "comprehension_result",
        sa.Column("model_name", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "comprehension_result",
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "comprehension_result",
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "comprehension_result",
        sa.Column(
            "key_point_coverage",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "comprehension_result",
        sa.Column("wrong_claim", sa.Text(), nullable=True),
    )
    op.add_column(
        "comprehension_result",
        sa.Column("similarity", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("comprehension_result", "similarity")
    op.drop_column("comprehension_result", "wrong_claim")
    op.drop_column("comprehension_result", "key_point_coverage")
    op.drop_column("comprehension_result", "reasons")
    op.drop_column("comprehension_result", "prompt_version")
    op.drop_column("comprehension_result", "model_name")
