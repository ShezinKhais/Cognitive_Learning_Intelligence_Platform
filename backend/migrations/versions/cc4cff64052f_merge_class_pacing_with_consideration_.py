"""merge class pacing with consideration evidence

Revision ID: cc4cff64052f
Revises: 1fc3b11e724a, a7b8c9d0e1f2
Create Date: 2026-11-14 13:52:22.843389

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "cc4cff64052f"
down_revision: str | Sequence[str] | None = ("1fc3b11e724a", "a7b8c9d0e1f2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
