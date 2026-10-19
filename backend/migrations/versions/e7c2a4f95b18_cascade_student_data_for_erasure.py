"""cascade student data for erasure

Revision ID: e7c2a4f95b18
Revises: d6b1f3a82e49
Create Date: 2026-10-16 10:00:00.000000

Erasing a student deletes the student record, and the database removes their
answers, labels, prompts and engagement with it. The account row stays, so the
audit log and consent records keep a valid reference.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c2a4f95b18"
down_revision: str | Sequence[str] | None = "d6b1f3a82e49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table, column, referenced table, referenced column, rule after this migration
FOREIGN_KEYS = [
    ("student_response", "student_id", "student", "student_id", "CASCADE"),
    ("dynamic_prompt", "student_id", "student", "student_id", "CASCADE"),
    ("engagement_record", "student_id", "student", "student_id", "CASCADE"),
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
