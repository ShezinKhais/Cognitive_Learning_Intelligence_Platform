"""Special consideration: a student asks, an administrator decides (General CS, Phase 8)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select, update

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.consideration_request import ConsiderationRequest
from app.models.student import Student
from app.realtime.classroom import classroom
from app.schemas.identity import Role
from app.services.consideration import ACCOMMODATION_TEXT

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
    assert student.accessibility_need == ACCOMMODATION_TEXT
    assert student.special_consideration_status == "approved"
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
