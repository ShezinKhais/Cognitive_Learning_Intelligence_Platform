"""Special consideration: a student asks, an administrator decides (General CS, Phase 8)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.consideration_request import ConsiderationRequest
from app.models.student import Student
from app.realtime import accommodations as accommodations_module
from app.realtime.accommodations import Accommodations
from app.realtime.classroom import classroom
from app.schemas.identity import Role
from app.services import consideration as consideration_service

from .session_support import add_course, enrol, sign_in_as

MINE = "/api/v1/me/consideration"
ADMIN = "/api/v1/admin/consideration-requests"


async def _student_row(factory) -> Student:  # noqa: ANN001
    async with factory() as session:
        return await session.scalar(select(Student).where(Student.user_id == STUDENT_ID))


async def _enrolled(db, app):  # noqa: ANN001, ANN202
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    # The development student's row is shared by every test, so each starts
    # from no request and no accommodation.
    async with factory() as session:
        student = await session.scalar(
            select(Student.student_id).where(Student.user_id == STUDENT_ID)
        )
        await session.execute(
            delete(ConsiderationRequest).where(ConsiderationRequest.student_id == student)
        )
        await session.execute(
            update(Student)
            .where(Student.student_id == student)
            .values(accessibility_need=None, special_consideration_status=None)
        )
        await session.commit()
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    return client, factory, course


async def test_a_request_is_sent_seen_by_an_admin_and_approved(db, app) -> None:  # noqa: ANN001
    client, factory, course = await _enrolled(db, app)
    classroom.accommodations.set(STUDENT_ID, False)

    assert client.get(MINE).json() == {"current": None}
    sent = client.post(
        MINE, json={"needs": ["camera", "pace", "camera"], "note": "  Doctor's letter on file  "}
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "pending"
    assert sent.json()["needs"] == ["camera", "pace"]
    assert sent.json()["note"] == "Doctor's letter on file"

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    listed = client.get(ADMIN).json()
    mine = next(item for item in listed["items"] if item["id"] == sent.json()["id"])
    assert mine["course_code"] == course.code

    approved = client.post(f"{ADMIN}/{mine['id']}/approve", json={"note": "Approved for term"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    student = await _student_row(factory)
    # The accommodation lives on the request; the student's own record of a
    # need is not the request's to write.
    assert student.accessibility_need is None
    # Honoured by a class the student is in now, not only from the next join.
    assert STUDENT_ID in classroom.accommodations

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(MINE).json()["current"]["decision_note"] == "Approved for term"


async def test_only_one_request_waits_at_a_time_and_it_can_be_withdrawn(db, app) -> None:  # noqa: ANN001
    client, _, _ = await _enrolled(db, app)
    assert client.post(MINE, json={"needs": ["prompts"]}).status_code == 201
    assert client.post(MINE, json={"needs": ["gaze"]}).status_code == 409

    assert client.post(f"{MINE}/withdraw").json()["status"] == "withdrawn"
    assert client.post(f"{MINE}/withdraw").status_code == 409
    assert client.post(MINE, json={"needs": ["gaze"]}).status_code == 201


async def test_a_refusal_changes_nothing_about_the_student(db, app) -> None:  # noqa: ANN001
    client, factory, _ = await _enrolled(db, app)
    before = await _student_row(factory)
    request_id = client.post(MINE, json={"needs": ["pace"]}).json()["id"]

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    assert client.post(f"{ADMIN}/{request_id}/reject", json={}).json()["status"] == "rejected"
    # A decided request cannot be decided again.
    assert client.post(f"{ADMIN}/{request_id}/approve", json={}).status_code == 409

    after = await _student_row(factory)
    assert after.accessibility_need == before.accessibility_need
    assert after.special_consideration_status == before.special_consideration_status


async def test_bad_requests_are_refused(db, app) -> None:  # noqa: ANN001
    client, _, _ = await _enrolled(db, app)
    assert client.post(MINE, json={"needs": []}).status_code == 422
    assert client.post(MINE, json={"needs": ["telepathy"]}).status_code == 422
    assert client.post(MINE, json={"needs": ["pace"], "note": "x" * 501}).status_code == 422
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    assert client.post(MINE, json={"needs": ["pace"], "until": yesterday}).status_code == 422


async def test_lecturers_reach_neither_side(db, app) -> None:  # noqa: ANN001
    client, _, _ = await _enrolled(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.get(MINE).status_code == 403
    assert client.get(ADMIN).status_code == 403


def _advance_to(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    for module in (accommodations_module, consideration_service):
        monkeypatch.setattr(module, "_today", lambda: day)


async def _approved_until(client, app, until: date):  # noqa: ANN001, ANN202
    request_id = client.post(MINE, json={"needs": ["camera"], "until": until.isoformat()}).json()[
        "id"
    ]
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    assert client.post(f"{ADMIN}/{request_id}/approve", json={}).status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    return request_id


async def test_an_approval_ends_on_its_last_day(db, app, monkeypatch) -> None:  # noqa: ANN001
    client, factory, _ = await _enrolled(db, app)
    classroom.accommodations.set(STUDENT_ID, False)
    today = datetime.now(UTC).date()
    last = today + timedelta(days=28)
    await _approved_until(client, app, last)

    async with factory() as session:
        assert (await consideration_service.in_force(session, STUDENT_ID)) is not None
    assert STUDENT_ID in classroom.accommodations

    _advance_to(monkeypatch, last)
    assert STUDENT_ID in classroom.accommodations

    # The day after, a class already running stops honouring it, and a fresh
    # join finds nothing in force.
    _advance_to(monkeypatch, last + timedelta(days=1))
    assert STUDENT_ID not in classroom.accommodations
    assert STUDENT_ID not in classroom.accommodations.members()
    async with factory() as session:
        assert (await consideration_service.in_force(session, STUDENT_ID)) is None


async def test_an_open_ended_approval_does_not_lapse(db, app, monkeypatch) -> None:  # noqa: ANN001
    client, factory, _ = await _enrolled(db, app)
    request_id = client.post(MINE, json={"needs": ["pace"]}).json()["id"]
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    assert client.post(f"{ADMIN}/{request_id}/approve", json={}).status_code == 200

    _advance_to(monkeypatch, datetime.now(UTC).date() + timedelta(days=400))
    assert STUDENT_ID in classroom.accommodations
    async with factory() as session:
        assert (await consideration_service.in_force(session, STUDENT_ID)) is not None


async def test_a_request_past_its_last_day_cannot_be_approved(db, app, monkeypatch) -> None:  # noqa: ANN001
    client, factory, _ = await _enrolled(db, app)
    classroom.accommodations.set(STUDENT_ID, False)
    last = datetime.now(UTC).date() + timedelta(days=3)
    request_id = client.post(MINE, json={"needs": ["gaze"], "until": last.isoformat()}).json()["id"]

    _advance_to(monkeypatch, last + timedelta(days=1))
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    late = client.post(f"{ADMIN}/{request_id}/approve", json={})
    assert late.status_code == 409
    assert STUDENT_ID not in classroom.accommodations
    # It can still be refused, so it does not sit pending forever.
    assert client.post(f"{ADMIN}/{request_id}/reject", json={}).json()["status"] == "rejected"


async def test_a_need_recorded_another_way_outlives_the_request(db, app, monkeypatch) -> None:  # noqa: ANN001
    client, factory, _ = await _enrolled(db, app)
    async with factory() as session:
        await session.execute(
            update(Student)
            .where(Student.user_id == STUDENT_ID)
            .values(accessibility_need="screen reader")
        )
        await session.commit()
    last = datetime.now(UTC).date() + timedelta(days=7)
    await _approved_until(client, app, last)

    _advance_to(monkeypatch, last + timedelta(days=1))
    student = await _student_row(factory)
    assert student.accessibility_need == "screen reader"
    async with factory() as session:
        assert await accommodations_module.has_accommodation(session, STUDENT_ID) is True


def test_granting_never_shortens_an_accommodation_already_held() -> None:
    registry = Accommodations()
    a = STUDENT_ID
    registry.set(a, True)
    registry.grant(a, date(2000, 1, 1))
    assert a in registry

    registry.set(a, True, until=date(2999, 1, 1))
    registry.grant(a, date(2998, 1, 1))
    assert a in registry
    registry.grant(a, None)
    registry.grant(a, date(2000, 1, 1))
    assert a in registry


async def test_the_database_holds_one_waiting_request_per_student(db, app) -> None:  # noqa: ANN001
    from sqlalchemy.exc import IntegrityError

    client, factory, _ = await _enrolled(db, app)
    assert client.post(MINE, json={"needs": ["pace"]}).status_code == 201
    async with factory() as session:
        student = await session.scalar(
            select(Student.student_id).where(Student.user_id == STUDENT_ID)
        )
        session.add(ConsiderationRequest(student_id=student, needs=["gaze"], status="pending"))
        with pytest.raises(IntegrityError):
            await session.flush()
