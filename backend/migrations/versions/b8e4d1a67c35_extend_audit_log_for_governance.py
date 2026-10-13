"""extend audit log for governance

Revision ID: b8e4d1a67c35
Revises: a3f6c8d2e591
Create Date: 2026-10-13 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b8e4d1a67c35"
down_revision: str | Sequence[str] | None = "a3f6c8d2e591"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("audit_log", "user_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("audit_log", "ip_address", existing_type=sa.String(length=45), nullable=True)
    op.add_column("audit_log", sa.Column("target_type", sa.String(length=50), nullable=True))
    op.add_column("audit_log", sa.Column("target_id", sa.UUID(), nullable=True))
    op.add_column(
        "audit_log",
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(op.f("ix_audit_log_timestamp"), "audit_log", ["timestamp"], unique=False)
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    user_id and ip_address stay nullable: an audit row is never deleted to make
    a constraint fit, and system entries have neither.
    """
    op.drop_index("ix_audit_log_target", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_timestamp"), table_name="audit_log")
    op.drop_column("audit_log", "details")
    op.drop_column("audit_log", "target_id")
    op.drop_column("audit_log", "target_type")
