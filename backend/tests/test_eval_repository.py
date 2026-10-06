"""Stored evaluation answers and classifier runs, against a real database."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.classifier_eval import ClassifierEvalPrediction, ClassifierEvalRun
from app.models.eval_answer import EvalAnswer
from app.repositories.eval_repository import (
    EvalPrediction,
    compare_runs,
    save_eval_run,
    set_final_label,
    upsert_eval_answers,
)

from .database_support import require_database


@pytest.fixture
async def database():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def evals(database):
    """Three stored answers and a model name unique to the test. Everything
    they leave behind is removed afterwards."""
    tag = uuid.uuid4().hex[:8]
    ids = [f"t{tag}-{n}" for n in (1, 2, 3)]
    labels = ["mastered", "partial", "struggling"]
    rows = [
        {
            "answer_id": answer_id,
            "question_key": "q1",
            "question_text": "What does logistic regression predict?",
            "reference_answer": "A probability.",
            "key_points": ["It predicts a probability"],
            "student_answer": f"answer {n}",
            "label_luna": label,
            "label_nour": "",
            "notes": "",
        }
        for n, (answer_id, label) in enumerate(zip(ids, labels, strict=True), start=1)
    ]
    async with database() as db:
        await upsert_eval_answers(db, rows)
        await db.commit()
    model = f"test-model-{tag}"

    yield SimpleNamespace(ids=ids, labels=labels, rows=rows, model=model)

    async with database() as db:
        await db.execute(delete(ClassifierEvalRun).where(ClassifierEvalRun.model_name == model))
        await db.execute(delete(EvalAnswer).where(EvalAnswer.answer_id.in_(ids)))
        await db.commit()


def predictions(evals, predicted):
    return [
        EvalPrediction(answer_id=i, human_label=h, predicted_label=p, confidence=c)
        for i, h, (p, c) in zip(evals.ids, evals.labels, predicted, strict=True)
    ]


async def run(database, evals, predicted, **overrides):
    fields = {
        "model_name": evals.model,
        "prompt_version": "free-text-v3",
        "label_column": "label_luna",
        "predictions": predictions(evals, predicted),
        "macro_f1": 0.5,
    }
    fields.update(overrides)
    async with database() as db:
        stored = await save_eval_run(db, **fields)
        await db.commit()
        return stored.run_id


async def test_answers_are_stored_with_blank_cells_as_no_label(database, evals):
    async with database() as db:
        rows = list(await db.scalars(select(EvalAnswer).where(EvalAnswer.answer_id.in_(evals.ids))))
    assert len(rows) == 3
    first = next(r for r in rows if r.answer_id == evals.ids[0])
    assert (first.label_luna, first.label_nour, first.label_final, first.notes) == (
        "mastered",
        None,
        None,
        None,
    )
    assert first.key_points == ["It predicts a probability"]


async def test_loading_answers_again_updates_labels_without_duplicates(database, evals):
    async with database() as db:
        await upsert_eval_answers(
            db, [{"answer_id": evals.ids[0], "label_nour": "partial", "notes": "unsure"}]
        )
        await db.commit()

    async with database() as db:
        rows = list(await db.scalars(select(EvalAnswer).where(EvalAnswer.answer_id.in_(evals.ids))))
    assert len(rows) == 3
    first = next(r for r in rows if r.answer_id == evals.ids[0])
    assert (first.label_nour, first.notes) == ("partial", "unsure")
    assert first.label_luna == "mastered"
    assert first.student_answer == "answer 1"


async def test_a_final_label_can_be_set_once_agreed(database, evals):
    async with database() as db:
        assert await set_final_label(db, evals.ids[1], "mastered") is True
        assert await set_final_label(db, "no-such-answer", "mastered") is False
        await db.commit()

    async with database() as db:
        answer = await db.get(EvalAnswer, evals.ids[1])
    assert answer.label_final == "mastered"


async def test_a_run_gets_its_counts_and_accuracy_from_its_predictions(database, evals):
    run_id = await run(
        database,
        evals,
        [("mastered", 0.9), ("mastered", 0.6), (None, None)],
        per_label={"mastered": {"precision": 0.5, "recall": 1.0, "f1": 0.67, "support": 1}},
        confidence_separation=0.75,
        embedding_model="nomic-embed-text",
    )

    async with database() as db:
        stored = await db.get(ClassifierEvalRun, run_id)
        rows = list(
            await db.scalars(
                select(ClassifierEvalPrediction).where(ClassifierEvalPrediction.run_id == run_id)
            )
        )
    assert (stored.answers_total, stored.answers_marked) == (3, 2)
    assert stored.accuracy == pytest.approx(1 / 3)
    assert (stored.model_name, stored.prompt_version) == (evals.model, "free-text-v3")
    assert stored.per_label["mastered"]["recall"] == 1.0
    assert stored.confidence_separation == 0.75
    assert sorted((r.predicted_label, r.correct) for r in rows if r.predicted_label) == [
        ("mastered", False),
        ("mastered", True),
    ]
    unreadable = next(r for r in rows if r.predicted_label is None)
    assert unreadable.correct is False


async def test_runs_are_compared_by_model_and_prompt_version(database, evals):
    await run(database, evals, [("mastered", 0.9)] * 3, prompt_version="free-text-v2")
    await run(database, evals, [("mastered", 0.9)] * 3, prompt_version="free-text-v3")
    await run(
        database,
        evals,
        [("mastered", 0.9)] * 3,
        prompt_version="free-text-v3",
        label_column="label_nour",
    )

    async with database() as db:
        everything = [r for r in await compare_runs(db) if r.model_name == evals.model]
        luna_only = [
            r
            for r in await compare_runs(db, label_column="label_luna")
            if r.model_name == evals.model
        ]
    assert [r.prompt_version for r in everything] == [
        "free-text-v2",
        "free-text-v3",
        "free-text-v3",
    ]
    assert [r.prompt_version for r in luna_only] == ["free-text-v2", "free-text-v3"]


async def test_a_run_with_no_predictions_is_refused(database, evals):
    async with database() as db:
        with pytest.raises(ValueError):
            await save_eval_run(
                db,
                model_name=evals.model,
                prompt_version="free-text-v3",
                label_column="label_luna",
                predictions=[],
                macro_f1=0.0,
            )


async def test_one_prediction_per_answer_in_a_run(database, evals):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_eval_run(
                db,
                model_name=evals.model,
                prompt_version="free-text-v3",
                label_column="label_luna",
                predictions=[
                    EvalPrediction(evals.ids[0], "mastered", "mastered"),
                    EvalPrediction(evals.ids[0], "mastered", "partial"),
                ],
                macro_f1=0.0,
            )


async def test_a_label_outside_the_three_is_refused(database, evals):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await set_final_label(db, evals.ids[0], "excellent")


async def test_labels_for_an_answer_that_is_not_stored_are_refused(database, evals):
    async with database() as db:
        with pytest.raises(ValueError):
            await upsert_eval_answers(
                db, [{"answer_id": "no-such-answer", "label_nour": "partial"}]
            )
