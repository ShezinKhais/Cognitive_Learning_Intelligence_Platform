"""Listing and reading sessions, and a session's answers, against a real database."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.schemas.identity import Role

from .session_support import (
    add_course,
    add_lecturer,
    add_question,
    create_session,
    enrol,
    sign_in_as,
)


async def _answer(factory, session_id, question_id, user_id) -> None:
    async with factory() as seed:
        student_id = (
            await seed.execute(select(Student.student_id).where(Student.user_id == user_id))
        ).scalar_one()
        seed.add(
            StudentResponse(
                session_id=session_id,
                student_id=student_id,
                question_id=question_id,
                selected_option=1,
                is_correct=True,
                elapsed_ms=900,
            )
        )
        await seed.commit()


async def test_a_lecturer_lists_only_their_own_sessions(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    other = await add_lecturer(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    mine = create_session(client, course, "Mine")
    sign_in_as(app, other, Role.LECTURER)
    create_session(client, course, "Theirs")

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    page = client.get("/api/v1/sessions").json()

    ids = [item["id"] for item in page["items"]]
    assert mine["id"] in ids
    assert all(item["lecturer_id"] == str(LECTURER_ID) for item in page["items"])
    assert page["total"] == len(ids)


async def test_an_admin_lists_every_session(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    other = await add_lecturer(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    first = create_session(client, course, "One")
    sign_in_as(app, other, Role.LECTURER)
    second = create_session(client, course, "Two")

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    ids = [item["id"] for item in client.get("/api/v1/sessions").json()["items"]]

    assert {first["id"], second["id"]} <= set(ids)


async def test_a_student_lists_only_sessions_of_their_course(db, app) -> None:
    client, factory, created = db
    enrolled_on = await add_course(factory, created)
    elsewhere = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    here = create_session(client, enrolled_on, "Here")
    away = create_session(client, elsewhere, "Away")
    await enrol(factory, enrolled_on)

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    ids = [item["id"] for item in client.get("/api/v1/sessions").json()["items"]]

    assert here["id"] in ids
    assert away["id"] not in ids


async def test_listing_is_paged_newest_first(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    for title, day in (("Early", "2026-01-05"), ("Late", "2026-03-05")):
        response = client.post(
            "/api/v1/sessions",
            json={"course_code": course.code, "title": title, "starts_at": f"{day}T09:00:00Z"},
        )
        assert response.status_code == 201

    page = client.get("/api/v1/sessions?limit=1").json()

    assert page["limit"] == 1
    assert page["items"][0]["starts_at"] >= "2026-03-05"
    assert page["total"] >= 2


async def test_a_session_is_read_by_its_owner_and_hidden_from_others(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    other = await add_lecturer(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    own = client.get(f"/api/v1/sessions/{session['id']}")
    assert own.status_code == 200
    assert own.json()["title"] == "Week 1"

    sign_in_as(app, other, Role.LECTURER)
    assert client.get(f"/api/v1/sessions/{session['id']}").status_code == 404
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.get(f"/api/v1/sessions/{uuid4()}").status_code == 404


async def test_a_student_cannot_read_a_session_of_another_course(db, app) -> None:
    client, factory, created = db
    enrolled_on = await add_course(factory, created)
    elsewhere = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    away = create_session(client, elsewhere)
    await enrol(factory, enrolled_on)

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(f"/api/v1/sessions/{away['id']}").status_code == 404


async def test_responses_are_all_for_staff_and_only_their_own_for_a_student(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    await enrol(factory, course)
    question_id = await add_question(db, course, LECTURER_ID)
    await _answer(factory, session["id"], question_id, STUDENT_ID)

    staff = client.get(f"/api/v1/sessions/{session['id']}/responses").json()
    assert staff["total"] == 1
    assert staff["items"][0]["selected_option"] == 1
    assert staff["items"][0]["is_correct"] is True

    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    own = client.get(f"/api/v1/sessions/{session['id']}/responses").json()
    assert own["total"] == 1


async def test_responses_of_a_hidden_session_are_not_found(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    other = await add_lecturer(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)

    sign_in_as(app, other, Role.LECTURER)
    assert client.get(f"/api/v1/sessions/{session['id']}/responses").status_code == 404
