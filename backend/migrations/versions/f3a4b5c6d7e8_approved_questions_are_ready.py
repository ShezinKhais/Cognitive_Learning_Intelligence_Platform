"""Approved questions are ready to send.

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6

Approving a question now stores it as staged, ready to send, instead of
waiting for a second "make ready" step. Questions approved before that
change are moved on the same way, so none is left waiting for a step that
no longer exists. Nothing reached a class from the approved state, so no
class history changes.
"""

from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE question SET status = 'staged' WHERE status = 'approved'")


def downgrade() -> None:
    # Which staged questions were approved before this revision is not
    # recorded, and both states mean the lecturer accepted the question,
    # so they stay staged.
    pass
