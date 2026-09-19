"""add phase four teams integration tables

Revision ID: 698c7dde1422
Revises: 372fd81eddf8
Create Date: 2026-09-19 16:37:16.062715

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "698c7dde1422"
down_revision: str | Sequence[str] | None = "372fd81eddf8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "teams_user_mapping",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("teams_user_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teams_user_id"),
    )
    op.create_index(
        op.f("ix_teams_user_mapping_user_id"), "teams_user_mapping", ["user_id"], unique=True
    )
    op.create_table(
        "roster_sync_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("unmatched_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_roster_sync_event_session_id"), "roster_sync_event", ["session_id"], unique=False
    )
    op.create_table(
        "teams_meeting",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("teams_meeting_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["session.session_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teams_meeting_id"),
    )
    op.create_index(
        op.f("ix_teams_meeting_session_id"), "teams_meeting", ["session_id"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_teams_meeting_session_id"), table_name="teams_meeting")
    op.drop_table("teams_meeting")
    op.drop_index(op.f("ix_roster_sync_event_session_id"), table_name="roster_sync_event")
    op.drop_table("roster_sync_event")
    op.drop_index(op.f("ix_teams_user_mapping_user_id"), table_name="teams_user_mapping")
    op.drop_table("teams_user_mapping")
