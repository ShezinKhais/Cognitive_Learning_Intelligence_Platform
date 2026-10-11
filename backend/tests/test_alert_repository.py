"""Stored AI alerts: saving, acknowledging and listing, against a real database."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.ai_alert import AIAlert
from app.models.course import Course
from app.models.session import Session
from app.models.user import User
from app.repositories.alert_repository import acknowledge_alert, list_alerts, save_alert

from .database_support import require_database


@pytest.fixture
async def database():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def live_session(database):
    """A live session with two lecturers. Everything it creates is removed
    afterwards."""
    async with database() as db:
        first = User(name="Alert Lecturer", role="lecturer", email=f"a-{uuid.uuid4()}@example.com")
        second = User(name="Other Lecturer", role="lecturer", email=f"b-{uuid.uuid4()}@example.com")
        course = Course(code=f"AL-{uuid.uuid4().hex[:8]}", name="Alert Repository")
        db.add_all([first, second, course])
        await db.flush()
        session = Session(
            instructor_id=first.user_id,
            course_id=course.id,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(hours=1),
            mode="live",
            status="active",
        )
        db.add(session)
        await db.commit()
        ids = SimpleNamespace(
            session=session.session_id,
            course=course.id,
            first=first.user_id,
            second=second.user_id,
        )

    yield ids

    async with database() as db:
        await db.execute(delete(AIAlert).where(AIAlert.session_id == ids.session))
        await db.execute(delete(Session).where(Session.session_id == ids.session))
        await db.execute(delete(Course).where(Course.id == ids.course))
        await db.execute(delete(User).where(User.user_id.in_([ids.first, ids.second])))
        await db.commit()


def alert_fields(ids, **overrides):
    fields = {
        "session_id": ids.session,
        "kind": "topic_difficulty",
        "message": "Much of the class is struggling on Odds ratios.",
        "reason": "6 of 8 classified answers were partial or struggling.",
        "confidence": 0.8,
    }
    fields.update(overrides)
    return fields


async def test_an_alert_is_stored_open_with_its_reason_and_version(database, live_session):
    async with database() as db:
        await save_alert(
            db,
            **alert_fields(
                live_session,
                topic="Odds ratios",
                model_name="qwen2.5:3b",
                prompt_version="free-text-v3",
                details={"respondents": 8, "threshold": 0.5},
            ),
        )
        await db.commit()

    async with database() as db:
        [alert] = await list_alerts(db, live_session.session)
    assert alert.status == "open"
    assert (alert.acknowledged_by, alert.acknowledged_at) == (None, None)
    assert alert.reason == "6 of 8 classified answers were partial or struggling."
    assert (alert.topic, alert.model_name, alert.prompt_version) == (
        "Odds ratios",
        "qwen2.5:3b",
        "free-text-v3",
    )
    assert alert.details == {"respondents": 8, "threshold": 0.5}


async def test_an_alert_keeps_its_explanation_and_recommendation(database, live_session):
    reasons = ["8 students answered.", "The classifier agreed on 6 of 8."]
    async with database() as db:
        await save_alert(
            db,
            **alert_fields(
                live_session,
                explanation="Most answers confused odds with probability.",
                explanation_source="ai",
                confidence_reasons=reasons,
                recommendation="Re-teach odds versus probability with one example.",
            ),
        )
        await db.commit()

    async with database() as db:
        [alert] = await list_alerts(db, live_session.session)
    assert alert.explanation == "Most answers confused odds with probability."
    assert alert.explanation_source == "ai"
    assert alert.confidence_reasons == reasons
    assert alert.recommendation == "Re-teach odds versus probability with one example."


async def test_an_alert_without_explanation_fields_stores_empty_defaults(database, live_session):
    async with database() as db:
        await save_alert(db, **alert_fields(live_session))
        await db.commit()

    async with database() as db:
        [alert] = await list_alerts(db, live_session.session)
    assert (alert.explanation, alert.explanation_source, alert.recommendation) == (None, None, None)
    assert alert.confidence_reasons == []


async def test_an_unknown_explanation_source_is_refused(database, live_session):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_alert(db, **alert_fields(live_session, explanation_source="guess"))


async def test_the_id_shown_to_the_lecturer_is_the_stored_id(database, live_session):
    shown = uuid.uuid4()
    async with database() as db:
        await save_alert(db, alert_id=shown, **alert_fields(live_session))
        await db.commit()

    async with database() as db:
        [alert] = await list_alerts(db, live_session.session)
    assert alert.alert_id == shown


async def test_acknowledging_records_who_and_when(database, live_session):
    async with database() as db:
        alert = await save_alert(db, **alert_fields(live_session))
        await db.commit()
        alert_id = alert.alert_id

    async with database() as db:
        done = await acknowledge_alert(db, alert_id, live_session.first)
        await db.commit()

    assert done is not None
    assert (done.status, done.acknowledged_by) == ("acknowledged", live_session.first)
    assert done.acknowledged_at is not None


async def test_a_second_acknowledgement_keeps_the_first(database, live_session):
    async with database() as db:
        alert = await save_alert(db, **alert_fields(live_session))
        await db.commit()
        alert_id = alert.alert_id
    async with database() as db:
        first = await acknowledge_alert(db, alert_id, live_session.first)
        await db.commit()

    async with database() as db:
        again = await acknowledge_alert(db, alert_id, live_session.second)
        await db.commit()

    assert again.acknowledged_by == live_session.first
    assert again.acknowledged_at == first.acknowledged_at


async def test_acknowledging_an_unknown_alert_returns_nothing(database, live_session):
    async with database() as db:
        assert await acknowledge_alert(db, uuid.uuid4(), live_session.first) is None


async def test_alerts_can_be_listed_by_status(database, live_session):
    async with database() as db:
        done = await save_alert(db, **alert_fields(live_session, message="Seen"))
        await save_alert(db, **alert_fields(live_session, message="Not yet seen"))
        await db.commit()
        done_id = done.alert_id
    async with database() as db:
        await acknowledge_alert(db, done_id, live_session.first)
        await db.commit()

    async with database() as db:
        everything = await list_alerts(db, live_session.session)
        still_open = await list_alerts(db, live_session.session, status="open")

    assert sorted(a.message for a in everything) == ["Not yet seen", "Seen"]
    assert [a.message for a in still_open] == ["Not yet seen"]


@pytest.mark.parametrize("reason", ["", "   "])
async def test_an_alert_without_a_reason_is_refused(database, live_session, reason):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_alert(db, **alert_fields(live_session, reason=reason))


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
async def test_a_confidence_outside_zero_to_one_is_refused(database, live_session, confidence):
    async with database() as db:
        with pytest.raises(IntegrityError):
            await save_alert(db, **alert_fields(live_session, confidence=confidence))
