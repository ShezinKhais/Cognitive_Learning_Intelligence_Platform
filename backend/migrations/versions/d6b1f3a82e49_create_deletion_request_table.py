"""create deletion request table

Revision ID: d6b1f3a82e49
Revises: c5a9e2f1d874
Create Date: 2026-10-13 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d6b1f3a82e49"
down_revision: str | Sequence[str] | None = "c5a9e2f1d874"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "deletion_request",
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="requested", nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_by", sa.UUID(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('session', 'student')", name="ck_deletion_request_target_type"
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'executed')",
            name="ck_deletion_request_status",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["user.user_id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["user.user_id"]),
        sa.ForeignKeyConstraint(["executed_by"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        op.f("ix_deletion_request_status"), "deletion_request", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_deletion_request_requested_by"),
        "deletion_request",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        "ix_deletion_request_target",
        "deletion_request",
        ["target_type", "target_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_deletion_request_target", table_name="deletion_request")
    op.drop_index(op.f("ix_deletion_request_requested_by"), table_name="deletion_request")
    op.drop_index(op.f("ix_deletion_request_status"), table_name="deletion_request")
    op.drop_table("deletion_request")
