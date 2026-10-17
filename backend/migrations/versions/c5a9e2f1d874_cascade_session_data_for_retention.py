"""cascade session data for retention

Revision ID: c5a9e2f1d874
Revises: b8e4d1a67c35
Create Date: 2026-10-13 15:00:00.000000

Deleting a session now removes everything it holds, which is what the 90-day
retention purge relies on. Questions are lecturer content, so they stay and
only lose their link to the session.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5a9e2f1d874"
down_revision: str | Sequence[str] | None = "b8e4d1a67c35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table, column, referenced table, referenced column, rule after this migration
FOREIGN_KEYS = [
    ("student_response", "session_id", "session", "session_id", "CASCADE"),
    ("comprehension_result", "response_id", "student_response", "response_id", "CASCADE"),
    ("dynamic_prompt", "session_id", "session", "session_id", "CASCADE"),
    ("engagement_record", "session_id", "session", "session_id", "CASCADE"),
    ("breakout_room", "session_id", "session", "session_id", "CASCADE"),
    ("question", "session_id", "session", "session_id", "SET NULL"),
]


def _set_rule(table: str, column: str, target: str, target_column: str, rule: str | None) -> None:
    """Replace the foreign key on table.column, found by its columns, not its name."""
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table):
        if foreign_key["constrained_columns"] == [column]:
            op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
    op.create_foreign_key(
        f"{table}_{column}_fkey", table, target, [column], [target_column], ondelete=rule
    )


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, target, target_column, rule in FOREIGN_KEYS:
        _set_rule(table, column, target, target_column, rule)


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, target, target_column, _ in FOREIGN_KEYS:
        _set_rule(table, column, target, target_column, None)
