"""enforce unique course code

Revision ID: c67d0d8ae17d
Revises: 62e9a85c991c
Create Date: 2026-08-15 19:24:21.980579

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c67d0d8ae17d"
down_revision: str | Sequence[str] | None = "62e9a85c991c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT code
                    FROM course
                    GROUP BY code
                    HAVING COUNT(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'duplicate course codes must be cleaned before migration';
                END IF;
            END
            $$;
            """
        )
    )

    op.create_index(
        "ix_course_code",
        "course",
        ["code"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_course_code",
        table_name="course",
    )
