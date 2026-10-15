# ruff: noqa: F811 - the fixtures come from test_comprehension_writer
"""A free-text answer in a live class is marked once stored, and the label
kept where topics, alerts and reports read it.

Owner: General CS, Phase 8, wiring AI 1's classifier to BBIS's store.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import update

from app.models.question import Question
from app.schemas.session import ComprehensionLabel
from app.services import free_text_marking, live_wiring
from app.services.free_text_classifier import Classification, Coverage, FreeTextQuestion

from .test_comprehension_writer import answer, database, labels_for, question  # noqa: F401

REFERENCE = "A network passes values through layers of weighted nodes."
KEY_POINTS = ["layers", "weights"]


class _Marker:
    model = "test-model"

    def __init__(self, fail: bool = False) -> None:
        self.seen: list[tuple[FreeTextQuestion, str]] = []
        self._fail = fail

    async def classify(self, asked: FreeTextQuestion, said: str) -> Classification:
        self.seen.append((asked, said))
        if self._fail:
            raise RuntimeError("the model is down")
        return Classification(
            label=ComprehensionLabel.PARTIAL,
            confidence=0.7,
            score=0.5,
            coverage=(Coverage.COVERED, Coverage.MISSED),
            wrong_claim=None,
            reasons=("Covers layers, not weights.",),
            feedback="Say what the weights do.",
            similarity=0.61,
            model=self.model,
        )


@pytest.fixture
async def free_text(database, question, monkeypatch):  # noqa: ANN001, ANN201, F811
    """The fixture's question as a free-text one the classifier can mark."""
    monkeypatch.setattr(free_text_marking, "get_session_factory", lambda: database)
    async with database() as db:
        await db.execute(
            update(Question)
            .where(Question.question_id == question.question)
            .values(
                question_type="free_text",
                options=None,
                correct_option=None,
                reference_answer=REFERENCE,
                key_points=KEY_POINTS,
            )
        )
        await db.commit()
    return question


async def _settled() -> None:
    while free_text_marking._marking:  # noqa: SLF001
        await asyncio.gather(*free_text_marking._marking, return_exceptions=True)  # noqa: SLF001


async def test_a_stored_free_text_answer_is_marked_and_its_label_kept(
    database,
    free_text,
    monkeypatch,  # noqa: ANN001, F811
) -> None:
    marker = _Marker()
    monkeypatch.setattr(free_text_marking, "classifier", lambda: marker)

    stored = await live_wiring._store_response(**answer(free_text, free_text="Layers of nodes."))  # noqa: SLF001
    await _settled()

    [(seen, said)] = marker.seen
    assert (seen.reference_answer, seen.key_points, said) == (
        REFERENCE,
        tuple(KEY_POINTS),
        "Layers of nodes.",
    )
    [row] = await labels_for(database, stored.response_id)
    assert (row.label, row.confidence_score, row.model_name) == ("partial", 0.7, "test-model")
    assert row.key_point_coverage == ["covered", "missed"]
    assert row.ai_feedback_text == "Say what the weights do."


async def test_a_failed_marking_leaves_the_answer_unlabelled(
    database,
    free_text,
    monkeypatch,  # noqa: ANN001, F811
) -> None:
    monkeypatch.setattr(free_text_marking, "classifier", lambda: _Marker(fail=True))

    stored = await live_wiring._store_response(**answer(free_text, free_text="Layers."))  # noqa: SLF001
    await _settled()

    assert await labels_for(database, stored.response_id) == []


async def test_a_question_without_key_points_is_not_sent_to_the_model(
    database,
    free_text,
    monkeypatch,  # noqa: ANN001, F811
) -> None:
    marker = _Marker()
    monkeypatch.setattr(free_text_marking, "classifier", lambda: marker)
    async with database() as db:
        await db.execute(
            update(Question).where(Question.question_id == free_text.question).values(key_points=[])
        )
        await db.commit()

    stored = await live_wiring._store_response(**answer(free_text, free_text="Layers."))  # noqa: SLF001
    await _settled()

    assert marker.seen == []
    assert await labels_for(database, stored.response_id) == []


async def test_a_scored_answer_is_not_marked_again(database, question, monkeypatch) -> None:  # noqa: ANN001, F811
    marker = _Marker()
    monkeypatch.setattr(free_text_marking, "classifier", lambda: marker)

    await live_wiring._store_response(**answer(question, selected_option=1, is_correct=True))  # noqa: SLF001
    await _settled()

    assert marker.seen == []
