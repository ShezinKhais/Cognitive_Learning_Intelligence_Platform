"""one comprehension label per response

Revision ID: b3c1e7a9d204
Revises: 7fb1c9da741b
Create Date: 2026-09-28 19:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c1e7a9d204"
down_revision: str | Sequence[str] | None = "7fb1c9da741b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A response written before this constraint may have been labelled more
    # than once. The reader already counts only the newest label, so that is
    # the one kept.
    op.execute(
        """
        DELETE FROM comprehension_result AS older
        USING comprehension_result AS newer
        WHERE older.response_id = newer.response_id
          AND (older.created_at, older.result_id) < (newer.created_at, newer.result_id)
        """
    )
    op.drop_index(op.f("ix_comprehension_result_response_id"), table_name="comprehension_result")
    op.create_index(
        op.f("ix_comprehension_result_response_id"),
        "comprehension_result",
        ["response_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_comprehension_result_response_id"), table_name="comprehension_result")
    op.create_index(
        op.f("ix_comprehension_result_response_id"),
        "comprehension_result",
        ["response_id"],
        unique=False,
    )
