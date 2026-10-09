"""add explanation columns to ai_alert

Revision ID: d5a2f8c61e47
Revises: a91c4e7d3b60
Create Date: 2026-10-07 12:00:00.000000

Every live alert now carries an explanation, where it came from, the reasons
behind its confidence and a recommendation. They are kept as columns so a
lecturer can review why an alert was raised after the live event.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d5a2f8c61e47"
down_revision: str | Sequence[str] | None = "a91c4e7d3b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ai_alert", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("ai_alert", sa.Column("explanation_source", sa.String(length=20), nullable=True))
    op.add_column(
        "ai_alert",
        sa.Column(
            "confidence_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("ai_alert", sa.Column("recommendation", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_ai_alert_explanation_source",
        "ai_alert",
        "explanation_source IN ('ai', 'fallback')",
    )
    op.create_check_constraint(
        "ck_ai_alert_confidence_reasons_array",
        "ai_alert",
        "jsonb_typeof(confidence_reasons) = 'array'",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_ai_alert_confidence_reasons_array", "ai_alert", type_="check")
    op.drop_constraint("ck_ai_alert_explanation_source", "ai_alert", type_="check")
    op.drop_column("ai_alert", "recommendation")
    op.drop_column("ai_alert", "confidence_reasons")
    op.drop_column("ai_alert", "explanation_source")
    op.drop_column("ai_alert", "explanation")
