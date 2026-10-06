"""create classifier evaluation tables

Revision ID: a91c4e7d3b60
Revises: f58a3c9d2e17
Create Date: 2026-10-07 00:00:00.000000

The hand-labelled answers the free-text classifier is measured against, and
one row per evaluation run with its accuracy and per-label scores, so runs
can be compared across model and prompt versions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a91c4e7d3b60"
down_revision: str | Sequence[str] | None = "f58a3c9d2e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABELS = "('mastered', 'partial', 'struggling')"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "eval_answer",
        sa.Column("answer_id", sa.String(length=20), nullable=False),
        sa.Column("question_key", sa.String(length=20), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column(
            "key_points",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("student_answer", sa.Text(), nullable=False),
        sa.Column("label_luna", sa.String(length=20), nullable=True),
        sa.Column("label_nour", sa.String(length=20), nullable=True),
        sa.Column("label_final", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            f"label_luna IS NULL OR label_luna IN {LABELS}", name="ck_eval_answer_luna"
        ),
        sa.CheckConstraint(
            f"label_nour IS NULL OR label_nour IN {LABELS}", name="ck_eval_answer_nour"
        ),
        sa.CheckConstraint(
            f"label_final IS NULL OR label_final IN {LABELS}", name="ck_eval_answer_final"
        ),
        sa.PrimaryKeyConstraint("answer_id"),
    )
    op.create_index(op.f("ix_eval_answer_question_key"), "eval_answer", ["question_key"])

    op.create_table(
        "classifier_eval_run",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("model_name", sa.String(length=150), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("embedding_model", sa.String(length=150), nullable=True),
        sa.Column("label_column", sa.String(length=30), nullable=False),
        sa.Column("answers_total", sa.Integer(), nullable=False),
        sa.Column("answers_marked", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("macro_f1", sa.Float(), nullable=False),
        sa.Column(
            "per_label",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence_separation", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "accuracy >= 0 AND accuracy <= 1", name="ck_classifier_eval_run_accuracy"
        ),
        sa.CheckConstraint(
            "macro_f1 >= 0 AND macro_f1 <= 1", name="ck_classifier_eval_run_macro_f1"
        ),
        sa.CheckConstraint(
            "answers_marked >= 0 AND answers_marked <= answers_total",
            name="ck_classifier_eval_run_counts",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        op.f("ix_classifier_eval_run_model_name"), "classifier_eval_run", ["model_name"]
    )
    op.create_index(
        op.f("ix_classifier_eval_run_prompt_version"), "classifier_eval_run", ["prompt_version"]
    )

    op.create_table(
        "classifier_eval_prediction",
        sa.Column("prediction_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("answer_id", sa.String(length=20), nullable=False),
        sa.Column("predicted_label", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("human_label", sa.String(length=20), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            f"predicted_label IS NULL OR predicted_label IN {LABELS}",
            name="ck_classifier_eval_prediction_predicted",
        ),
        sa.CheckConstraint(f"human_label IN {LABELS}", name="ck_classifier_eval_prediction_human"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_classifier_eval_prediction_confidence",
        ),
        sa.CheckConstraint(
            "correct = (predicted_label IS NOT NULL AND predicted_label = human_label)",
            name="ck_classifier_eval_prediction_correct",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["classifier_eval_run.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["answer_id"], ["eval_answer.answer_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("prediction_id"),
        sa.UniqueConstraint("run_id", "answer_id", name="uq_classifier_eval_prediction_run_answer"),
    )
    op.create_index(
        op.f("ix_classifier_eval_prediction_run_id"), "classifier_eval_prediction", ["run_id"]
    )
    op.create_index(
        op.f("ix_classifier_eval_prediction_answer_id"),
        "classifier_eval_prediction",
        ["answer_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_classifier_eval_prediction_answer_id"), table_name="classifier_eval_prediction"
    )
    op.drop_index(
        op.f("ix_classifier_eval_prediction_run_id"), table_name="classifier_eval_prediction"
    )
    op.drop_table("classifier_eval_prediction")
    op.drop_index(op.f("ix_classifier_eval_run_prompt_version"), table_name="classifier_eval_run")
    op.drop_index(op.f("ix_classifier_eval_run_model_name"), table_name="classifier_eval_run")
    op.drop_table("classifier_eval_run")
    op.drop_index(op.f("ix_eval_answer_question_key"), table_name="eval_answer")
    op.drop_table("eval_answer")
