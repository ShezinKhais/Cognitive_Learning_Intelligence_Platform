"""Remember which class meetings the calendar sweep put C.L.I.P into."""

import sqlalchemy as sa
from alembic import op

revision = "c3a7e91d5b20"
down_revision = "f4c5d6e7a8b9"  # after course_requests
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "teams_auto_join",
        sa.Column("chat_thread", sa.String(512), primary_key=True),
        sa.Column("tenant_id", sa.String(256), nullable=False),
        sa.Column("tab_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notice_owed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade():
    op.drop_table("teams_auto_join")
