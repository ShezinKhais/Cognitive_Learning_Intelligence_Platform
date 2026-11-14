"""Track checkpoint source identity for copies."""

import sqlalchemy as sa
from alembic import op

revision = "1a9ce4d70b52"
down_revision = "e9a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("question", sa.Column("source_question_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_question_source_question_id",
        "question",
        "question",
        ["source_question_id"],
        ["question_id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_question_source_question_id", "question", ["source_question_id"])
    # Plans saved before this migration have no lineage. Only infer it when
    # one earlier, eligible bank entry exactly matches the saved snapshot.
    op.execute("""
        UPDATE question AS copy
        SET source_question_id = (
            SELECT (array_agg(source.question_id))[1]
            FROM question AS source
            WHERE source.source_material_id = copy.source_material_id
              AND source.created_at < copy.created_at
              AND (source.session_id IS NULL OR source.status = 'delivered')
              AND source.status IN ('approved', 'staged', 'delivered')
              AND ROW(source.question_text, source.question_type, source.difficulty,
                      source.options, source.correct_option, source.topic,
                      source.source_slide, source.source_excerpt,
                      source.reference_answer, source.key_points)
                  IS NOT DISTINCT FROM
                  ROW(copy.question_text, copy.question_type, copy.difficulty,
                      copy.options, copy.correct_option, copy.topic,
                      copy.source_slide, copy.source_excerpt,
                      copy.reference_answer, copy.key_points)
            HAVING count(*) = 1
        )
        FROM session
        WHERE copy.session_id = session.session_id
          AND session.question_selection_enabled
          AND session.status = 'prepared'
    """)


def downgrade():
    op.drop_index("ix_question_source_question_id", table_name="question")
    op.drop_constraint("fk_question_source_question_id", "question", type_="foreignkey")
    op.drop_column("question", "source_question_id")
