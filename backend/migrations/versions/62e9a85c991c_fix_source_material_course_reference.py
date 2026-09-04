"""fix source material course reference

Revision ID: 62e9a85c991c
Revises: 97e029d1159d
Create Date: 2026-08-14 15:26:51.802581

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "62e9a85c991c"
down_revision: str | Sequence[str] | None = "97e029d1159d"
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
                    SELECT 1
                    FROM source_material
                    WHERE course_id IS NOT NULL
                ) THEN
                    RAISE EXCEPTION
                        'non-null source_material.course_id values require UUID mapping';
                END IF;
            END
            $$;
            """
        )
    )

    op.alter_column(
        "source_material",
        "course_id",
        existing_type=sa.Integer(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="NULL::uuid",
    )
    op.create_foreign_key(
        "fk_source_material_course_id_course",
        "source_material",
        "course",
        ["course_id"],
        ["id"],
    )
    op.create_index(
        "ix_source_material_course_id",
        "source_material",
        ["course_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM source_material
                    WHERE course_id IS NOT NULL
                ) THEN
                    RAISE EXCEPTION
                        'non-null source_material.course_id values cannot revert to integer';
                END IF;
            END
            $$;
            """
        )
    )

    op.drop_index(
        "ix_source_material_course_id",
        table_name="source_material",
    )
    op.drop_constraint(
        "fk_source_material_course_id_course",
        "source_material",
        type_="foreignkey",
    )
    op.alter_column(
        "source_material",
        "course_id",
        existing_type=sa.UUID(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="NULL::integer",
    )
