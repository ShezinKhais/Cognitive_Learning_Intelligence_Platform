"""Stores the hand-labelled evaluation answers and each classifier evaluation run.

Owner: BBIS, Phase 5. Each function works inside the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classifier_eval import ClassifierEvalPrediction, ClassifierEvalRun
from app.models.eval_answer import EvalAnswer

_FIELDS = (
    "question_key",
    "question_text",
    "reference_answer",
    "key_points",
    "student_answer",
    "label_luna",
    "label_nour",
    "label_final",
    "notes",
)
# An empty cell in the labelling sheet means no label or no note yet.
_BLANK_IS_NONE = ("label_luna", "label_nour", "label_final", "notes")


@dataclass(frozen=True)
class EvalPrediction:
    answer_id: str
    # The label the run is scored against.
    human_label: str
    # None when the model's reply could not be read.
    predicted_label: str | None
    confidence: float | None = None


# What a row must carry to be added as a new answer.
_REQUIRED = ("question_key", "question_text", "reference_answer", "student_answer")


async def upsert_eval_answers(db: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> int:
    """Add or refresh labelled answers, matched on answer_id, and return how many.

    A row with every required field is added, or refreshed if the answer is
    already stored. A row with only some fields, such as new labels for an
    answer, updates the stored answer and leaves its other fields alone. It
    raises ValueError for an answer that is not stored.
    """
    for row in rows:
        answer_id = row["answer_id"]
        values = {}
        for field in _FIELDS:
            if field in row:
                value = row[field]
                if field in _BLANK_IS_NONE and isinstance(value, str):
                    value = value.strip() or None
                values[field] = value
        if all(field in values for field in _REQUIRED):
            await db.execute(
                insert(EvalAnswer)
                .values(answer_id=answer_id, **values)
                .on_conflict_do_update(index_elements=[EvalAnswer.answer_id], set_=values)
            )
        elif values:
            result = await db.execute(
                update(EvalAnswer).where(EvalAnswer.answer_id == answer_id).values(**values)
            )
            if result.rowcount == 0:
                raise ValueError(f"answer {answer_id} is not stored and the row is incomplete")
    return len(rows)


async def set_final_label(db: AsyncSession, answer_id: str, label: str) -> bool:
    """Record the label the two labellers agreed. Returns whether the answer exists."""
    result = await db.execute(
        update(EvalAnswer).where(EvalAnswer.answer_id == answer_id).values(label_final=label)
    )
    return result.rowcount > 0


async def list_eval_answers(db: AsyncSession) -> list[EvalAnswer]:
    rows = await db.scalars(select(EvalAnswer).order_by(EvalAnswer.answer_id))
    return list(rows)


async def save_eval_run(
    db: AsyncSession,
    *,
    model_name: str,
    prompt_version: str,
    label_column: str,
    predictions: Sequence[EvalPrediction],
    macro_f1: float,
    per_label: dict[str, Any] | None = None,
    confidence_separation: float | None = None,
    embedding_model: str | None = None,
    notes: str | None = None,
) -> ClassifierEvalRun:
    """Store one evaluation run and its predictions.

    The counts and accuracy come from the predictions, so a run cannot
    disagree with its own rows. An answer whose model reply was unreadable
    counts as wrong. macro_f1, per_label and confidence_separation come from
    the evaluation functions the caller already ran.
    """
    if not predictions:
        raise ValueError("an evaluation run needs at least one prediction")
    right = [
        p.predicted_label is not None and p.predicted_label == p.human_label for p in predictions
    ]
    run = ClassifierEvalRun(
        model_name=model_name,
        prompt_version=prompt_version,
        embedding_model=embedding_model,
        label_column=label_column,
        answers_total=len(predictions),
        answers_marked=sum(p.predicted_label is not None for p in predictions),
        accuracy=sum(right) / len(predictions),
        macro_f1=macro_f1,
        per_label=per_label or {},
        confidence_separation=confidence_separation,
        notes=notes,
    )
    db.add(run)
    await db.flush()
    db.add_all(
        ClassifierEvalPrediction(
            run_id=run.run_id,
            answer_id=p.answer_id,
            predicted_label=p.predicted_label,
            confidence=p.confidence,
            human_label=p.human_label,
            correct=ok,
        )
        for p, ok in zip(predictions, right, strict=True)
    )
    await db.flush()
    return run


async def compare_runs(
    db: AsyncSession, *, label_column: str | None = None
) -> list[ClassifierEvalRun]:
    """Runs grouped by model and prompt version, newest first within each."""
    query = select(ClassifierEvalRun)
    if label_column is not None:
        query = query.where(ClassifierEvalRun.label_column == label_column)
    rows = await db.scalars(
        query.order_by(
            ClassifierEvalRun.model_name,
            ClassifierEvalRun.prompt_version,
            ClassifierEvalRun.created_at.desc(),
        )
    )
    return list(rows)
