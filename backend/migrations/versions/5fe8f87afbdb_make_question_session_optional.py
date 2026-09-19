"""make question session optional

Revision ID: 5fe8f87afbdb
Revises: b47a09538015
Create Date: 2026-09-18 00:00:00.000000

Questions are generated when a lecturer uploads material, which is before any
class session exists, so question.session_id cannot be required. It is set
later, when a question is staged for a session. Who may review a question is
decided by who uploaded its material (source_material.uploaded_by_user_id),
not by a session's instructor.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5fe8f87afbdb"
down_revision: str | Sequence[str] | None = "b47a09538015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("question", "session_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    """Downgrade schema.

    Refused while any question has no session. Filling one in would invent a
    session the question never belonged to, and deleting them would destroy a
    lecturer's reviewed questions.
    """
    unassigned = (
        op.get_bind()
        .execute(sa.text("select count(*) from question where session_id is null"))
        .scalar_one()
    )
    if unassigned:
        raise RuntimeError(
            f"{unassigned} question(s) have no session; assign or remove them before "
            "downgrading past 5fe8f87afbdb"
        )
    op.alter_column("question", "session_id", existing_type=sa.UUID(), nullable=False)
