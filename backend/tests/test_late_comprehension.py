# ruff: noqa: F811 - shared database fixtures
"""Actual database close/classification races must leave exactly one alert."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.models.ai_alert import AIAlert
from app.models.delivered_question import DeliveredQuestion
from app.realtime.classroom import classroom
from app.realtime.recorders import ClosedQuestion
from app.schemas.events import QuestionCloseReason
from app.services import comprehension_refresh, free_text_marking, live_wiring

from .test_comprehension_writer import answer, database, question  # noqa: F401
from .test_free_text_marking import _Marker, _settled, free_text  # noqa: F401


@pytest.fixture
async def delivered(database, free_text, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(comprehension_refresh, "get_session_factory", lambda: database)
    config = get_settings().model_copy(update={"comprehension_alert_min_respondents": 1})
    monkeypatch.setattr(comprehension_refresh, "get_settings", lambda: config)
    monkeypatch.setattr(classroom, "comprehension_refresher", comprehension_refresh.refresh)
    now = datetime.now(UTC)
    async with database() as db:
        db.add(
            DeliveredQuestion(
                session_id=free_text.session,
                question_id=free_text.question,
                delivered_at=now,
                closes_at=now + timedelta(seconds=30),
                window_seconds=30,
                eligible_count=1,
            )
        )
        await db.commit()
    yield free_text
    await _settled()
    async with database() as db:
        await db.execute(delete(AIAlert).where(AIAlert.session_id == free_text.session))
        await db.execute(
            delete(DeliveredQuestion).where(DeliveredQuestion.session_id == free_text.session)
        )
        await db.commit()


async def _close(ids):  # noqa: ANN001, ANN201
    await live_wiring._store_close(
        ClosedQuestion(
            session_id=ids.session,
            question_id=ids.question,
            reason=QuestionCloseReason.WINDOW_ELAPSED,
            closed_at=datetime.now(UTC),
            eligible=frozenset({ids.user}),
            answered=frozenset({ids.user}),
        )
    )


async def _alerts(factory, ids):  # noqa: ANN001, ANN201
    async with factory() as db:
        return (await db.scalars(select(AIAlert).where(AIAlert.session_id == ids.session))).all()


async def test_classification_after_close_creates_one_persisted_alert(
    database, delivered, monkeypatch
):  # noqa: ANN001, ANN201
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowMarker(_Marker):
        async def classify(self, asked, said):  # noqa: ANN001, ANN201
            entered.set()
            await release.wait()
            return await super().classify(asked, said)

    monkeypatch.setattr(free_text_marking, "classifier", SlowMarker)
    await live_wiring._store_response(**answer(delivered, free_text="Layers of nodes."))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await _close(delivered)
        assert await _alerts(database, delivered) == []
    finally:
        release.set()
        await _settled()
    assert len(await _alerts(database, delivered)) == 1
    # Repeated callbacks and concurrent retries cannot create a second alert.
    results = await asyncio.gather(
        *(comprehension_refresh.refresh(delivered.session, delivered.question) for _ in range(3))
    )
    assert results == [None, None, None]
    assert len(await _alerts(database, delivered)) == 1


async def test_classification_before_close_waits_for_the_recorded_close(
    database, delivered, monkeypatch
):  # noqa: ANN001, ANN201
    monkeypatch.setattr(free_text_marking, "classifier", _Marker)
    await live_wiring._store_response(**answer(delivered, free_text="Layers of nodes."))
    await _settled()
    assert await _alerts(database, delivered) == []
    await _close(delivered)
    [alert] = await _alerts(database, delivered)
    assert alert.details["respondents"] == 1


async def test_failed_explanation_keeps_a_safe_fallback_alert(database, delivered, monkeypatch):  # noqa: ANN001, ANN201
    def broken(evidence):  # noqa: ANN001, ANN201
        raise RuntimeError("explanation unavailable")

    monkeypatch.setattr(comprehension_refresh, "explain_topic_difficulty", broken)
    monkeypatch.setattr(free_text_marking, "classifier", _Marker)
    await live_wiring._store_response(**answer(delivered, free_text="Layers of nodes."))
    await _settled()
    await _close(delivered)
    [alert] = await _alerts(database, delivered)
    assert alert.explanation_source == "fallback"
    assert alert.explanation and alert.recommendation


async def test_competing_first_refreshes_store_exactly_one_alert(
    database,
    delivered,
    monkeypatch,  # noqa: ANN001
) -> None:
    monkeypatch.setattr(free_text_marking, "classifier", _Marker)
    await live_wiring._store_response(**answer(delivered, free_text="Layers of nodes."))
    await _settled()
    async with database() as db:
        await db.execute(
            update(DeliveredQuestion)
            .where(
                DeliveredQuestion.session_id == delivered.session,
                DeliveredQuestion.question_id == delivered.question,
            )
            .values(closed_at=datetime.now(UTC))
        )
        await db.commit()
    results = await asyncio.gather(
        *(comprehension_refresh.refresh(delivered.session, delivered.question) for _ in range(3))
    )
    assert sum(result is not None for result in results) == 1
    assert len(await _alerts(database, delivered)) == 1
