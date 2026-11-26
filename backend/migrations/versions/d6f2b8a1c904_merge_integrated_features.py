"""Merge chat history, Teams and account-recovery migrations.

Revision ID: d6f2b8a1c904
Revises: b28e1f7a9c32, c3a7e91d5b20, a15c0d1e2f36

This is a graph-only merge. Existing databases that already applied
chat history can still apply the other two migrations.
"""

revision = "d6f2b8a1c904"
down_revision = (
    "b28e1f7a9c32",
    "c3a7e91d5b20",
    "a15c0d1e2f36",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
