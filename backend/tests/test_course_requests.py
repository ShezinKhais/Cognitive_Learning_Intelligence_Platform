"""Lecturers asking for new courses, and admins approving or declining.

Owner: General CS, Phase 8.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.course_request import CourseRequest
from app.schemas.identity import Role

from .session_support import add_course, add_lecturer, sign_in_as


def _code() -> str:
    return f"ZR{uuid4().hex[:6].upper()}"


@pytest.fixture
async def asked(db):  # noqa: ANN001, ANN201
    """Codes asked for in a test, cleaned up with any course they became."""
    codes: list[str] = []
    yield codes
    _, factory, created = db
    async with factory() as cleanup:
        found = await cleanup.scalars(select(Course.id).where(Course.code.in_(codes)))
        created["course"].extend(found)
        await cleanup.execute(delete(CourseRequest).where(CourseRequest.code.in_(codes)))
        await cleanup.commit()


def _ask(client, codes, code=None, **extra):  # noqa: ANN001, ANN003, ANN202
    code = code or _code()
    codes.append(code.upper())
    return client.post(
        "/api/v1/courses/requests",
        json={"code": code, "name": "Applied Graph Theory", **extra},
    )


async def test_a_lecturer_asks_and_an_admin_approves(db, app, asked) -> None:
    client, factory, _ = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    made = _ask(client, asked, code=_code().lower(), reason="New elective this term")
    assert made.status_code == 201, made.text
    request = made.json()
    assert request["status"] == "pending" and request["code"] == asked[-1]

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    waiting = client.get("/api/v1/courses/requests", params={"status": "pending"}).json()
    assert request["id"] in [r["id"] for r in waiting]
    approved = client.post(
        f"/api/v1/admin/course-requests/{request['id']}/approve",
        json={"name": "Graph Theory"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    async with factory() as look:
        course = await look.scalar(select(Course).where(Course.code == asked[-1]))
        teaches = await look.scalar(
            select(CourseLecturer.user_id).where(CourseLecturer.course_id == course.id)
        )
    assert course.name == "Graph Theory"
    assert teaches == LECTURER_ID

    again = client.post(f"/api/v1/admin/course-requests/{request['id']}/decline", json={})
    assert again.status_code == 409


async def test_a_declined_request_keeps_the_note_for_the_lecturer(db, app, asked) -> None:
    client, _, _ = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    request = _ask(client, asked).json()
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    declined = client.post(
        f"/api/v1/admin/course-requests/{request['id']}/decline",
        json={"note": "This is taught under CSIT321."},
    )
    assert declined.status_code == 200

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    mine = {r["id"]: r for r in client.get("/api/v1/courses/requests").json()}
    assert mine[request["id"]]["status"] == "declined"
    assert mine[request["id"]]["decision_note"] == "This is taught under CSIT321."


async def test_a_code_that_exists_or_is_waiting_is_refused(db, app, asked) -> None:
    client, factory, created = db
    existing = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert _ask(client, asked, code=existing.code).status_code == 409
    code = _code()
    assert _ask(client, asked, code=code).status_code == 201
    assert _ask(client, asked, code=code).status_code == 409
    assert _ask(client, asked, code="has space").status_code == 422


async def test_a_lecturer_sees_only_their_own_requests(db, app, asked) -> None:
    client, factory, created = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    mine = _ask(client, asked).json()
    sign_in_as(app, await add_lecturer(factory, created), Role.LECTURER)
    theirs = _ask(client, asked).json()

    seen = [r["id"] for r in client.get("/api/v1/courses/requests").json()]
    assert theirs["id"] in seen and mine["id"] not in seen


async def test_only_an_admin_decides_and_a_student_cannot_ask(db, app, asked) -> None:
    client, _, _ = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    request = _ask(client, asked).json()
    approve = f"/api/v1/admin/course-requests/{request['id']}/approve"
    assert client.post(approve, json={}).status_code == 403

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert _ask(client, asked).status_code == 403
    assert client.get("/api/v1/courses/requests").status_code == 403


async def test_approving_a_code_an_admin_added_meanwhile_joins_that_course(db, app, asked) -> None:
    client, factory, created = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    request = _ask(client, asked).json()
    async with factory() as seed:
        course = Course(code=asked[-1], name="Added by hand")
        seed.add(course)
        await seed.commit()
    created["course"].append(course.id)

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    approved = client.post(f"/api/v1/admin/course-requests/{request['id']}/approve", json={})
    assert approved.status_code == 200

    async with factory() as look:
        teaches = await look.scalar(
            select(CourseLecturer.user_id).where(CourseLecturer.course_id == course.id)
        )
        kept = await look.scalar(select(Course.name).where(Course.id == course.id))
    assert teaches == LECTURER_ID
    assert kept == "Added by hand"


async def test_an_admin_renames_a_course_but_not_its_code(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    renamed = client.patch(f"/api/v1/admin/courses/{course.code.lower()}", json={"name": "New"})

    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {"id": str(course.id), "code": course.code, "name": "New"}
    assert client.patch("/api/v1/admin/courses/NOPE999", json={"name": "x"}).status_code == 404
