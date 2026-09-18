"""add material progress percent check

Revision ID: b47a09538015
Revises: 2d155233838b
Create Date: 2026-09-18 00:00:00.000000

MaterialProcessingStatus declares ck_material_processing_status_percent, but
b5c496365765 created the table with only the stage and sequence checks, so a
migrated database accepted a percent of 150 that the model says it cannot
hold. This adds the check the model already describes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b47a09538015"
down_revision: str | Sequence[str] | None = "2d155233838b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        "ck_material_processing_status_percent",
        "material_processing_status",
        "percent >= 0 AND percent <= 100",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_material_processing_status_percent",
        "material_processing_status",
        type_="check",
    )
