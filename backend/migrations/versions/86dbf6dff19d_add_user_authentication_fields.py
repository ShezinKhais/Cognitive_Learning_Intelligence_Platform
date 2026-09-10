"""add user authentication fields

Revision ID: 86dbf6dff19d
Revises: c67d0d8ae17d
Create Date: 2026-08-15 20:44:02.485861

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86dbf6dff19d"
down_revision: str | Sequence[str] | None = "c67d0d8ae17d"
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
                    SELECT role
                    FROM "user"
                    WHERE role NOT IN ('student', 'lecturer', 'admin')
                ) THEN
                    RAISE EXCEPTION
                        'invalid user roles must be cleaned before migration';
                END IF;
            END
            $$;
            """
        )
    )

    op.add_column(
        "user",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_user_role",
        "user",
        "role IN ('student', 'lecturer', 'admin')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_user_role",
        "user",
        type_="check",
    )
    op.drop_column("user", "active")
    op.drop_column("user", "password_hash")
