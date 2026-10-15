"""Persist authenticated bot conversation references for checkpoint notifications."""

import sqlalchemy as sa
from alembic import op

revision = "b74d1c93ea20"
down_revision = "a3f6c8d2e591"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams_meeting_link", sa.Column("bot_service_url", sa.String(512)))
    op.add_column("teams_meeting_link", sa.Column("bot_conversation_id", sa.String(512)))
    op.add_column("teams_meeting_link", sa.Column("bot_tenant_id", sa.String(256)))


def downgrade() -> None:
    for name in ("bot_tenant_id", "bot_conversation_id", "bot_service_url"):
        op.drop_column("teams_meeting_link", name)
