"""add material warnings

Revision ID: f7a642ce1edf
Revises: 5fe8f87afbdb
Create Date: 2026-09-18 00:00:00.000000

MaterialOut carries the warnings processing raised for the lecturer (a page
that could not be read, a dropped draft question, generation that failed),
but source_material had nowhere to keep them, so they were lost the moment the
progress stream ended. They are stored as a JSON array of strings.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f7a642ce1edf"
down_revision: str | Sequence[str] | None = "5fe8f87afbdb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "source_material",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_material", "warnings")
