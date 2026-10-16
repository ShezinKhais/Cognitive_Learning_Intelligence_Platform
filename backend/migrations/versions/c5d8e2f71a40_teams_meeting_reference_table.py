"""Keep the bot's meeting reference per meeting, apart from the session link.

Revision ID: c5d8e2f71a40
Revises: b74d1c93ea20

The reference lived on teams_meeting_link, so it could only be saved once a
meeting was linked, and re-linking (which replaces the link row) dropped it.
"""

import sqlalchemy as sa
from alembic import op

revision = "c5d8e2f71a40"
down_revision = "b74d1c93ea20"
branch_labels = None
depends_on = None

COLUMNS = ("bot_service_url", "bot_conversation_id", "bot_tenant_id")


def upgrade() -> None:
    op.create_table(
        "teams_meeting_reference",
        sa.Column("meeting_id", sa.String(256), primary_key=True),
        sa.Column("service_url", sa.String(512), nullable=False),
        sa.Column("conversation_id", sa.String(512), nullable=False),
        sa.Column("tenant_id", sa.String(256), nullable=False),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "INSERT INTO teams_meeting_reference (meeting_id, service_url, conversation_id, tenant_id)"
        " SELECT meeting_id, bot_service_url, bot_conversation_id, bot_tenant_id"
        " FROM teams_meeting_link"
        " WHERE bot_service_url IS NOT NULL AND bot_conversation_id IS NOT NULL"
        " AND bot_tenant_id IS NOT NULL"
    )
    for name in COLUMNS:
        op.drop_column("teams_meeting_link", name)


def downgrade() -> None:
    op.add_column("teams_meeting_link", sa.Column("bot_service_url", sa.String(512)))
    op.add_column("teams_meeting_link", sa.Column("bot_conversation_id", sa.String(512)))
    op.add_column("teams_meeting_link", sa.Column("bot_tenant_id", sa.String(256)))
    op.execute(
        "UPDATE teams_meeting_link AS link"
        " SET bot_service_url = ref.service_url, bot_conversation_id = ref.conversation_id,"
        " bot_tenant_id = ref.tenant_id"
        " FROM teams_meeting_reference AS ref WHERE ref.meeting_id = link.meeting_id"
    )
    op.drop_table("teams_meeting_reference")
