"""One waiting special consideration request per student.

Revision ID: e1f2a3b4c5d6
Revises: d8e3f4a5b6c7

The service refused a second waiting request after reading the latest one,
so two sent at once could both get through. A partial unique index makes it
the database's rule.
"""

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d8e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_consideration_request_one_pending",
        "consideration_request",
        ["student_id"],
        unique=True,
        postgresql_where="status = 'pending'",
    )


def downgrade() -> None:
    op.drop_index("uq_consideration_request_one_pending", table_name="consideration_request")
