"""store upload time with time zone

Revision ID: 63cc1030dce5
Revises: f7a642ce1edf
Create Date: 2026-09-18 00:00:00.000000

source_material.uploaded_at was the one timestamp in the schema without a time
zone. The upload response gave it in UTC with an offset, while every read of
the same material returned a bare timestamp that a client takes as its own
local time, several hours out wherever the client is not on UTC. Existing
values were written by the database's now() on a UTC server, so they are
converted as UTC.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "63cc1030dce5"
down_revision: str | Sequence[str] | None = "f7a642ce1edf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "source_material",
        "uploaded_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="uploaded_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "source_material",
        "uploaded_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="uploaded_at AT TIME ZONE 'UTC'",
    )
