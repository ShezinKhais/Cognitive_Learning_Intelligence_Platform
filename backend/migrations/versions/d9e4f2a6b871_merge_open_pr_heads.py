"""Join the migrations of #320, #324 and #326, which all follow f4c5d6e7a8b9.

Integration only: none of the three changes a table another one touches.
"""

revision = "d9e4f2a6b871"
down_revision = ("a15c0d1e2f36", "b28e1f7a9c32", "c3a7e91d5b20")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
