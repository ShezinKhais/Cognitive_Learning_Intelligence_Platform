"""Hand-labelled student answers, the accuracy baseline for the free-text classifier."""

from typing import Any

from sqlalchemy import CheckConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_LABELS = "('mastered', 'partial', 'struggling')"


class EvalAnswer(Base):
    __tablename__ = "eval_answer"
    __table_args__ = (
        CheckConstraint(
            f"label_luna IS NULL OR label_luna IN {_LABELS}", name="ck_eval_answer_luna"
        ),
        CheckConstraint(
            f"label_nour IS NULL OR label_nour IN {_LABELS}", name="ck_eval_answer_nour"
        ),
        CheckConstraint(
            f"label_final IS NULL OR label_final IN {_LABELS}", name="ck_eval_answer_final"
        ),
    )

    # The id used in tests/eval/answers_to_label.csv, such as a01.
    answer_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    question_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    student_answer: Mapped[str] = mapped_column(Text, nullable=False)
    label_luna: Mapped[str | None] = mapped_column(String(20), nullable=True)
    label_nour: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The label the two labellers agreed after discussing, once they have.
    label_final: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
