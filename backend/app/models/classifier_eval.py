"""Free-text classifier evaluation runs, comparable across model and prompt versions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_LABELS = "('mastered', 'partial', 'struggling')"


class ClassifierEvalRun(Base):
    __tablename__ = "classifier_eval_run"
    __table_args__ = (
        CheckConstraint("accuracy >= 0 AND accuracy <= 1", name="ck_classifier_eval_run_accuracy"),
        CheckConstraint("macro_f1 >= 0 AND macro_f1 <= 1", name="ck_classifier_eval_run_macro_f1"),
        CheckConstraint(
            "answers_marked >= 0 AND answers_marked <= answers_total",
            name="ck_classifier_eval_run_counts",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    model_name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Which human labels the run was scored against: label_luna, label_nour
    # or label_final.
    label_column: Mapped[str] = mapped_column(String(30), nullable=False)
    answers_total: Mapped[int] = mapped_column(Integer, nullable=False)
    # Answers the classifier returned a label for. The rest had an unreadable
    # model reply, and count as wrong in accuracy.
    answers_marked: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    macro_f1: Mapped[float] = mapped_column(Float, nullable=False)
    # Precision, recall, F1 and support for each label.
    per_label: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    # How well confidence ranks right labels above wrong ones, 0 to 1. Null
    # when every label was right or every one wrong.
    confidence_separation: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ClassifierEvalPrediction(Base):
    __tablename__ = "classifier_eval_prediction"
    __table_args__ = (
        UniqueConstraint("run_id", "answer_id", name="uq_classifier_eval_prediction_run_answer"),
        CheckConstraint(
            f"predicted_label IS NULL OR predicted_label IN {_LABELS}",
            name="ck_classifier_eval_prediction_predicted",
        ),
        CheckConstraint(f"human_label IN {_LABELS}", name="ck_classifier_eval_prediction_human"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_classifier_eval_prediction_confidence",
        ),
        # Right exactly when the classifier gave the human's label.
        CheckConstraint(
            "correct = (predicted_label IS NOT NULL AND predicted_label = human_label)",
            name="ck_classifier_eval_prediction_correct",
        ),
    )

    prediction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classifier_eval_run.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    answer_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("eval_answer.answer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null when the model's reply could not be read.
    predicted_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The human label this run was scored against, kept so the run stays
    # readable if the labels are later revised.
    human_label: Mapped[str] = mapped_column(String(20), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
