"""Stored AI recommendations: saving, acknowledging and listing, against a real database."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.repositories.alert_repository import save_alert
from app.repositories.recommendation_repository import (
    acknowledge_recommendation,
    list_recommendations,
    save_recommendation,
)

from .test_alert_repository import alert_fields, database, live_session  # noqa: F401


def fields(ids, **overrides):
    values = {
        "session_id": ids.session,
        "recommendation": "Revisit odds ratios with a worked example.",
        "reason": "6 of 8 classified answers on this topic were partial or struggling.",
        "confidence": 0.8,
    }
    values.update(overrides)
    return values


async def test_a_recommendation_is_stored_with_its_reason_sources_and_version(
    database,  # noqa: F811
    live_session,  # noqa: F811
):
    async with database() as db:
        alert = await save_alert(db, **alert_fields(live_session))
        await save_recommendation(
            db,
            **fields(
                live_session,
                alert_id=alert.alert_id,
                topic="Odds ratios",
                sources=[{"slide": 4, "excerpt": "If the OR is greater than 1..."}],
                model_name="qwen2.5:3b",
                prompt_version="recommend-v1",
            ),
        )
        await db.commit()
        alert_id = alert.alert_id

    async with database() as db:
        [row] = await list_recommendations(db, live_session.session)
    assert (row.status, row.used_fallback) == ("open", False)
    assert row.alert_id == alert_id
    assert row.sources == [{"slide": 4, "excerpt": "If the OR is greater than 1..."}]
    assert (row.topic, row.model_name, row.prompt_version) == (
        "Odds ratios",
        "qwen2.5:3b",
        "recommend-v1",
    )


async def test_a_fallback_recommendation_says_so_and_needs_no_model(
    database,  # noqa: F811
    live_session,  # noqa: F811
):
    async with database() as db:
        await save_recommendation(db, **fields(live_session, used_fallback=True))
        await db.commit()

    async with database() as db:
        [row] = await list_recommendations(db, live_session.session)
    assert row.used_fallback is True
    assert (row.model_name, row.prompt_version, row.sources) == (None, None, [])


async def test_acknowledging_keeps_the_first_lecturer(
    database,  # noqa: F811
    live_session,  # noqa: F811
):
    async with database() as db:
        row = await save_recommendation(db, **fields(live_session))
        await db.commit()
        recommendation_id = row.recommendation_id
    async with database() as db:
        first = await acknowledge_recommendation(db, recommendation_id, live_session.first)
        await db.commit()

    async with database() as db:
        again = await acknowledge_recommendation(db, recommendation_id, live_session.second)
        await db.commit()

    assert first.status == "acknowledged"
    assert again.acknowledged_by == live_session.first
    assert again.acknowledged_at == first.acknowledged_at


async def test_acknowledging_an_unknown_recommendation_returns_nothing(
    database,  # noqa: F811
    live_session,  # noqa: F811
):
    async with database() as db:
        assert await acknowledge_recommendation(db, uuid.uuid4(), live_session.first) is None


async def test_recommendations_can_be_listed_by_status(
    database,  # noqa: F811
    live_session,  # noqa: F811
):
    async with database() as db:
        done = await save_recommendation(db, **fields(live_session, recommendation="Seen"))
        await save_recommendation(db, **fields(live_session, recommendation="Not yet seen"))
        await db.commit()
        done_id = done.recommendation_id
    async with database() as db:
        await acknowledge_recommendation(db, done_id, live_session.first)
        await db.commit()

    async with database() as db:
        still_open = await list_recommendations(db, live_session.session, status="open")

    assert [r.recommendation for r in still_open] == ["Not yet seen"]


async def test_a_recommendation_outlives_its_alert(
    database,  # noqa: F811
    live_session,  # noqa: F811
):
    async with database() as db:
        alert = await save_alert(db, **alert_fields(live_session))
        await save_recommendation(db, **fields(live_session, alert_id=alert.alert_id))
        await db.commit()
        await db.delete(alert)
        await db.commit()

    async with database() as db:
        [row] = await list_recommendations(db, live_session.session)
    assert row.alert_id is None


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("column", ["recommendation", "reason"])
async def test_a_blank_recommendation_or_reason_is_refused(
    database,  # noqa: F811
    live_session,  # noqa: F811
    column,
    blank,
):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_recommendation(db, **fields(live_session, **{column: blank}))
