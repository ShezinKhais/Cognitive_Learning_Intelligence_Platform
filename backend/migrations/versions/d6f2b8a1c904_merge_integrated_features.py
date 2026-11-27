"""Merge chat history, Teams and account-recovery migrations.

Revision ID: d6f2b8a1c904
Revises: b28e1f7a9c32, d8e2b4f6a1c3

This graph-only merge joins chat history with the shared Teams and
account-recovery migration head from PR #331.
"""

revision = "d6f2b8a1c904"
down_revision = (
    "b28e1f7a9c32",
    "d8e2b4f6a1c3",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
