"""Store optional evidence with a special consideration request."""

import sqlalchemy as sa
from alembic import op

revision = "1fc3b11e724a"
down_revision = "1a9ce4d70b52"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("consideration_request", sa.Column("evidence_type", sa.String(30)))
    op.add_column("consideration_request", sa.Column("evidence", sa.LargeBinary()))


def downgrade():
    op.drop_column("consideration_request", "evidence")
    op.drop_column("consideration_request", "evidence_type")
