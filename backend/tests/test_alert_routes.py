"""Cyber 1, Phase 5: the lecturer's alerts survive a refresh and can be acknowledged.

Against a real database, as the routes are used. The rules under test: only the
lecturer who runs a session, or an admin, can read or acknowledge its alerts; an
alert is reached only through its own session; the first acknowledgement is
kept; and a stored alert always has something to read, whatever wrote it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.api.deps import get_principal
from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID, get_consent_repository
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models.ai_alert import AIAlert
from app.models.session import Session as SessionModel
from app.repositories import alert_repository
from app.schemas.identity import Role
from app.schemas.session import ClassComprehensionAlert
from app.services import alert_store

from .session_support import add_course, add_lecturer, add_question, create_session, sign_in_as


async def keep(factory, session_id: str | UUID, **overrides: Any) -> UUID:
    """A stored alert, as the live classroom leaves it."""
    fields: dict[str, Any] = {
        "kind": "topic_difficulty",
        "message": "Much of the class is struggling on Planets.",
        "reason": "4 of 6 classified answers were partial or struggling.",
        "confidence": 0.8,
        "topic": "Planets",
        "details": {
            "respondents": 6,
            "threshold": 0.5,
            "correct_ratio": 0.33,
            "explanation": "4 of 6 classified answers were partial or struggling.",
            "explanation_source": "fallback",
            "confidence_reasons": ["6 of 6 students shown the question have an answer."],
            "recommendation": "Re-teach Planets: most answers show the idea did not land.",
        },
    }
    fields.update(overrides)
    async with factory() as db:
        row = await alert_repository.save_alert(db, session_id=UUID(str(session_id)), **fields)
        await db.commit()
    return row.alert_id


def comprehension_alert(session_id: UUID, **overrides: Any) -> ClassComprehensionAlert:
    fields: dict[str, Any] = {
        "alert_id": uuid4(),
        "session_id": session_id,
        "question_id": uuid4(),
        "topic": "Planets",
        "correct_ratio": 0.25,
        "respondents": 8,
        "threshold": 0.5,
        "raised_at": datetime.now(UTC),
        "message": "Much of the class is struggling on Planets.",
        "reason": "6 of 8 classified answers were partial or struggling.",
        "confidence": 0.7,
        "explanation": "6 of 8 classified answers were partial or struggling (4 struggling).",
        "explanation_source": "fallback",
        "confidence_reasons": ["8 of 10 students shown the question have an answer."],
        "recommendation": "Re-teach Planets: most classified answers show the idea was missed.",
    }
    fields.update(overrides)
    return ClassComprehensionAlert(**fields)


@pytest.fixture
def lecturer_session(db, app):  # noqa: ANN201
    """A prepared session run by the development lecturer, signed in as them."""

    async def make():  # noqa: ANN202
        client, factory, created = db
        course = await add_course(factory, created)
        sign_in_as(app, LECTURER_ID, Role.LECTURER)
        return create_session(client, course)

    return make


def alerts_path(session_id: str) -> str:
    return f"/api/v1/sessions/{session_id}/alerts"


def ack_path(session_id: str, alert_id: UUID | str) -> str:
    return f"{alerts_path(session_id)}/{alert_id}/acknowledge"


# -- reading ----------------------------------------------------------------------


async def test_a_session_with_no_alerts_lists_none(db, lecturer_session) -> None:
    client, _, _ = db
    session = await lecturer_session()
    assert client.get(alerts_path(session["id"])).json() == []


async def test_the_stored_alert_is_listed_with_why_and_what_to_do(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])

    [alert] = client.get(alerts_path(session["id"])).json()

    assert alert["alert_id"] == str(alert_id)
    assert alert["session_id"] == session["id"]
    assert alert["kind"] == "topic_difficulty" and alert["topic"] == "Planets"
    assert alert["reason"] == "4 of 6 classified answers were partial or struggling."
    assert alert["explanation_source"] == "fallback"
    assert alert["recommendation"].startswith("Re-teach Planets")
    assert alert["confidence_reasons"] == ["6 of 6 students shown the question have an answer."]
    assert (alert["respondents"], alert["threshold"], alert["correct_ratio"]) == (6, 0.5, 0.33)
    assert alert["confidence"] == 0.8
    assert (alert["status"], alert["acknowledged_by"], alert["acknowledged_at"]) == (
        "open",
        None,
        None,
    )


async def test_alerts_come_oldest_first(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    first = await keep(factory, session["id"], message="First.")
    second = await keep(factory, session["id"], message="Second.")

    listed = [a["alert_id"] for a in client.get(alerts_path(session["id"])).json()]

    assert listed == [str(first), str(second)]


async def test_alerts_can_be_listed_by_status(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    seen, unseen = await keep(factory, session["id"]), await keep(factory, session["id"])
    assert client.post(ack_path(session["id"], seen)).status_code == 200

    open_ = client.get(alerts_path(session["id"]), params={"status": "open"}).json()
    done = client.get(alerts_path(session["id"]), params={"status": "acknowledged"}).json()

    assert [a["alert_id"] for a in open_] == [str(unseen)]
    assert [a["alert_id"] for a in done] == [str(seen)]
    assert client.get(alerts_path(session["id"]), params={"status": "bogus"}).status_code == 422


async def test_an_alert_the_classroom_stored_reads_back_as_it_was_shown(
    db, lecturer_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory, _ = db
    monkeypatch.setattr(alert_store, "get_session_factory", lambda: factory)
    session = await lecturer_session()
    question_id = await add_question(db, await add_course(factory, db[2]), LECTURER_ID)
    live = comprehension_alert(UUID(session["id"]), question_id=question_id)

    await alert_store.store_comprehension_alert(live)

    [alert] = client.get(alerts_path(session["id"])).json()
    assert alert["question_id"] == str(question_id)
    assert alert["alert_id"] == str(live.alert_id)
    for name in ("message", "reason", "explanation", "recommendation", "explanation_source"):
        assert alert[name] == getattr(live, name), name
    assert alert["confidence_reasons"] == live.confidence_reasons
    assert (alert["topic"], alert["respondents"], alert["threshold"]) == ("Planets", 8, 0.5)
    assert alert["correct_ratio"] == 0.25 and alert["confidence"] == 0.7
    assert alert["kind"] == "topic_difficulty" and alert["status"] == "open"


async def test_the_stored_row_carries_the_figures_and_explanation_in_its_details(
    db, lecturer_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, factory, _ = db
    monkeypatch.setattr(alert_store, "get_session_factory", lambda: factory)
    session = await lecturer_session()
    question_id = await add_question(db, await add_course(factory, db[2]), LECTURER_ID)
    live = comprehension_alert(UUID(session["id"]), question_id=question_id)

    await alert_store.store_comprehension_alert(live)

    async with factory() as check:
        row = await check.get(AIAlert, live.alert_id)
    assert row is not None and row.details == alert_store.alert_details(live)
    assert row.model_name is None and row.student_id is None


async def test_alerts_are_there_after_the_session_has_ended(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    async with factory() as end:
        await end.execute(
            update(SessionModel)
            .where(SessionModel.session_id == UUID(session["id"]))
            .values(status="ended")
        )
        await end.commit()

    assert [a["alert_id"] for a in client.get(alerts_path(session["id"])).json()] == [str(alert_id)]
    assert client.post(ack_path(session["id"], alert_id)).status_code == 200


# -- acknowledging ----------------------------------------------------------------


async def test_the_lecturer_acknowledges_an_alert(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])

    response = client.post(ack_path(session["id"], alert_id))

    assert response.status_code == 200, response.text
    alert = response.json()
    assert alert["status"] == "acknowledged"
    assert alert["acknowledged_by"] == str(LECTURER_ID)
    assert alert["acknowledged_at"] is not None
    # The reason and recommendation are still there, and it is kept.
    assert alert["reason"] and alert["recommendation"]
    [listed] = client.get(alerts_path(session["id"])).json()
    assert (listed["status"], listed["acknowledged_by"]) == ("acknowledged", str(LECTURER_ID))
    async with factory() as check:
        stored = await check.get(AIAlert, alert_id, populate_existing=True)
    assert stored is not None and stored.status == "acknowledged"
    assert stored.acknowledged_by == LECTURER_ID


async def test_acknowledging_twice_changes_nothing(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])

    first = client.post(ack_path(session["id"], alert_id)).json()
    again = client.post(ack_path(session["id"], alert_id))

    assert again.status_code == 200
    assert again.json()["acknowledged_at"] == first["acknowledged_at"]
    assert again.json()["acknowledged_by"] == first["acknowledged_by"]


async def test_the_first_acknowledgement_is_kept_when_an_admin_follows(
    db, app, lecturer_session
) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    first = client.post(ack_path(session["id"], alert_id)).json()
    assert first["acknowledged_by"] == str(LECTURER_ID)

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    second = client.post(ack_path(session["id"], alert_id))

    assert second.status_code == 200
    assert second.json()["acknowledged_by"] == str(LECTURER_ID)
    assert second.json()["acknowledged_at"] == first["acknowledged_at"]


async def test_two_acknowledgements_at_once_leave_one_winner(db, lecturer_session) -> None:
    _, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    a, b = LECTURER_ID, ADMIN_ID

    async def acknowledge(who: UUID):  # noqa: ANN202
        async with factory() as work:
            return await alert_store.acknowledge_session_alert(
                work, UUID(session["id"]), alert_id, who
            )

    first, second = await asyncio.gather(acknowledge(a), acknowledge(b))

    assert first.acknowledged_by == second.acknowledged_by
    assert first.acknowledged_by in (a, b)
    assert first.acknowledged_at == second.acknowledged_at
    # Committed by the service itself, not by whoever called it.
    async with factory() as check:
        stored = await check.get(AIAlert, alert_id, populate_existing=True)
    assert stored is not None and stored.status == "acknowledged"
    assert stored.acknowledged_by == first.acknowledged_by


async def test_an_alert_that_vanishes_while_being_acknowledged_is_not_found(
    db, lecturer_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])

    async def gone(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(alert_store.alert_repository, "acknowledge_alert", gone)

    async with factory() as work:
        with pytest.raises(NotFoundError):
            await alert_store.acknowledge_session_alert(
                work, UUID(session["id"]), alert_id, LECTURER_ID
            )


async def test_an_admin_may_read_and_acknowledge_any_lecturers_alerts(
    db, app, lecturer_session
) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])

    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    assert [a["alert_id"] for a in client.get(alerts_path(session["id"])).json()] == [str(alert_id)]
    acknowledged = client.post(ack_path(session["id"], alert_id))
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_by"] == str(ADMIN_ID)


# -- who may not -------------------------------------------------------------------


async def test_another_lecturer_cannot_read_or_acknowledge_them(db, app, lecturer_session) -> None:
    client, factory, created = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    sign_in_as(app, await add_lecturer(factory, created), Role.LECTURER)

    listing = client.get(alerts_path(session["id"]))
    acknowledging = client.post(ack_path(session["id"], alert_id))

    assert listing.status_code == acknowledging.status_code == 404
    # The same answer as for a session that does not exist, so ids cannot be probed.
    missing = client.get(alerts_path(str(uuid4())))
    assert missing.status_code == 404
    assert listing.json()["error"]["message"] == missing.json()["error"]["message"]
    async with factory() as check:
        stored = await check.get(AIAlert, alert_id, populate_existing=True)
    assert stored is not None and stored.status == "open" and stored.acknowledged_by is None


async def test_a_student_cannot_read_or_acknowledge_them(db, app, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    assert client.get(alerts_path(session["id"])).status_code == 403
    assert client.post(ack_path(session["id"], alert_id)).status_code == 403
    async with factory() as check:
        stored = await check.get(AIAlert, alert_id, populate_existing=True)
    assert stored is not None and stored.status == "open"


async def test_nobody_signed_out_can_read_or_acknowledge_them(db, app, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    app.dependency_overrides.pop(get_principal, None)

    assert client.get(alerts_path(session["id"])).status_code == 401
    assert client.post(ack_path(session["id"], alert_id)).status_code == 401


async def test_a_lecturer_without_terms_consent_is_refused(db, lecturer_session) -> None:
    client, factory, _ = db
    session = await lecturer_session()
    alert_id = await keep(factory, session["id"])
    get_consent_repository(get_settings()).clear()

    assert client.get(alerts_path(session["id"])).status_code == 403
    assert client.post(ack_path(session["id"], alert_id)).status_code == 403


async def test_an_alert_is_reached_only_through_its_own_session(db, app, lecturer_session) -> None:
    client, factory, created = db
    own = await lecturer_session()
    other_course = await add_course(factory, created)
    elsewhere = create_session(client, other_course, "Another class")
    alert_id = await keep(factory, elsewhere["id"])

    # The same lecturer owns both sessions, but the alert is not this one's.
    response = client.post(ack_path(own["id"], alert_id))

    assert response.status_code == 404
    assert client.get(alerts_path(own["id"])).json() == []
    async with factory() as check:
        stored = await check.get(AIAlert, alert_id, populate_existing=True)
    assert stored is not None and stored.status == "open"
    assert client.post(ack_path(elsewhere["id"], alert_id)).status_code == 200


async def test_an_alert_that_does_not_exist_is_not_found(db, lecturer_session) -> None:
    client, _, _ = db
    session = await lecturer_session()

    assert client.post(ack_path(session["id"], uuid4())).status_code == 404
    assert client.post(ack_path(session["id"], "not-a-uuid")).status_code == 422
    assert client.post(ack_path("not-a-uuid", uuid4())).status_code == 422


async def test_a_missing_session_is_not_found(db, app, lecturer_session) -> None:
    client, _, _ = db
    await lecturer_session()

    assert client.post(ack_path(str(uuid4()), uuid4())).status_code == 404


# -- reading a row nobody wrote carefully -------------------------------------------


def row(**overrides: Any) -> AIAlert:
    fields: dict[str, Any] = {
        "alert_id": uuid4(),
        "session_id": uuid4(),
        "question_id": None,
        "student_id": None,
        "kind": "topic_difficulty",
        "topic": "Planets",
        "message": "Much of the class is struggling.",
        "reason": "4 of 6 classified answers were partial or struggling.",
        "confidence": 0.5,
        "details": {},
        "status": "open",
        "raised_at": datetime.now(UTC),
        "acknowledged_by": None,
        "acknowledged_at": None,
    }
    fields.update(overrides)
    return AIAlert(**fields)


def assert_readable(alert) -> None:  # noqa: ANN001
    for text in (alert.message, alert.reason, alert.explanation, alert.recommendation):
        assert text.strip()
    assert alert.confidence_reasons and all(r.strip() for r in alert.confidence_reasons)
    assert alert.explanation_source in ("ai", "fallback")
    assert alert.status in ("open", "acknowledged")


BAD_DETAILS: list[Any] = [
    {},
    None,
    "junk",
    ["not", "a", "dict"],
    {
        "explanation": "",
        "recommendation": "   ",
        "confidence_reasons": [],
        "explanation_source": "",
    },
    {"explanation": 5, "recommendation": ["x"], "confidence_reasons": "no"},
    {"confidence_reasons": ["", "  ", 3, None]},
    {"explanation_source": "human", "respondents": "six", "threshold": True, "correct_ratio": None},
]


@pytest.mark.parametrize("details", BAD_DETAILS)
def test_a_stored_alert_with_missing_or_junk_details_still_has_something_to_read(
    details: Any,
) -> None:
    alert = alert_store.alert_from_row(row(details=details))
    assert_readable(alert)
    assert alert.explanation_source == "fallback"
    assert (alert.respondents, alert.threshold) == (None, None)


def test_an_alert_of_a_kind_nothing_knows_still_has_a_reason_and_a_recommendation() -> None:
    alert = alert_store.alert_from_row(row(kind="brand_new_kind", message="", reason=" x "))
    assert_readable(alert)
    assert alert.message == "Something needs your attention."
    assert alert.reason == "x"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_a_blank_reason_or_message_is_replaced_not_shown(blank: str) -> None:
    # The table refuses a blank reason, so this is the read side not trusting that.
    alert = alert_store.alert_from_row(row(reason=blank, message=blank))
    assert_readable(alert)
    assert (
        alert.reason == "The system flagged this automatically, but could not produce the detail."
    )
    assert alert.message == "Much of the class may be struggling with the last question."


def test_an_unknown_status_reads_as_open() -> None:
    assert alert_store.alert_from_row(row(status="weird")).status == "open"


@pytest.mark.parametrize(("stored", "shown"), [(1.7, 1.0), (-0.2, 0.0), (0.4, 0.4)])
def test_a_confidence_outside_zero_to_one_is_held_to_it(stored: float, shown: float) -> None:
    assert alert_store.alert_from_row(row(confidence=stored)).confidence == shown


def test_good_details_are_shown_exactly() -> None:
    details = alert_store.alert_details(comprehension_alert(uuid4()))
    alert = alert_store.alert_from_row(row(details=details, status="acknowledged",
                                           acknowledged_by=LECTURER_ID,
                                           acknowledged_at=datetime.now(UTC)))  # fmt: skip
    assert alert.explanation == details["explanation"]
    assert alert.recommendation == details["recommendation"]
    assert alert.confidence_reasons == details["confidence_reasons"]
    assert (alert.respondents, alert.threshold, alert.correct_ratio) == (8, 0.5, 0.25)
    assert alert.status == "acknowledged" and alert.acknowledged_by == LECTURER_ID


async def test_the_ai_label_survives_storage(
    db, lecturer_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory, _ = db
    monkeypatch.setattr(alert_store, "get_session_factory", lambda: factory)
    session = await lecturer_session()
    question_id = await add_question(db, await add_course(factory, db[2]), LECTURER_ID)

    await alert_store.store_comprehension_alert(
        comprehension_alert(UUID(session["id"]), question_id=question_id, explanation_source="ai")
    )

    assert client.get(alerts_path(session["id"])).json()[0]["explanation_source"] == "ai"


async def test_every_session_alert_query_is_scoped_to_its_session(db, lecturer_session) -> None:
    _, factory, created = db
    mine = await lecturer_session()
    other_course = await add_course(factory, created)
    theirs = create_session(db[0], other_course, "Elsewhere")
    await keep(factory, mine["id"])
    await keep(factory, theirs["id"])

    async with factory() as check:
        mine_only = await alert_store.list_session_alerts(check, UUID(mine["id"]))
        total = (await check.scalars(select(AIAlert.alert_id))).all()

    assert len(mine_only) == 1 and len(total) >= 2
