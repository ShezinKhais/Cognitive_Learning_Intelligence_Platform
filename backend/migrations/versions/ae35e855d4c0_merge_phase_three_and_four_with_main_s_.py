"""merge phase three and four with main's material and question updates

Revision ID: ae35e855d4c0
Revises: 63cc1030dce5, 698c7dde1422
Create Date: 2026-09-19 19:18:14.872586

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ae35e855d4c0"
down_revision: str | Sequence[str] | None = ("63cc1030dce5", "698c7dde1422")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
