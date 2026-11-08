"""The lecturer's pacing for a class: checkpoint spacing and answer time."""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "e2b3c4d5f6a7"
branch_labels = None
depends_on = None

COLUMNS = ("checkpoint_minutes", "answer_seconds")


def upgrade():
    for table in ("session", "course"):
        for name in COLUMNS:
            op.add_column(table, sa.Column(name, sa.Integer(), nullable=True))


def downgrade():
    for table in ("course", "session"):
        for name in reversed(COLUMNS):
            op.drop_column(table, name)
