"""Reading sessions and their responses through the routes, against a real
database: who sees which session, and whose answers.

Owner: BBIS (queries) and Cyber 1 (the rule), wired in Phase 8.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.auth.store import ADMIN_ID, LECTURER_ID, STUDENT_ID
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.schemas.identity import Role

from .session_support import (
    add_course,
    add_lecturer,
    add_question,
    create_session,
    enrol,
    sign_in_as,
)


def _ids(response) -> set[str]:  # noqa: ANN001
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


async def _two_lecturers_sessions(db, app):  # noqa: ANN001, ANN202
    client, factory, created = db
    mine_course = await add_course(factory, created)
    other_course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    mine = create_session(client, mine_course)
    other = await add_lecturer(factory, created)
    sign_in_as(app, other, Role.LECTURER)
    theirs = create_session(client, other_course)
    return mine_course, mine, other_course, theirs


async def _answer(db, session_id: str, student_id: UUID, question_id: UUID) -> None:  # noqa: ANN001
    _, factory, _ = db
    async with factory() as seed:
        seed.add(
            StudentResponse(
                session_id=UUID(session_id),
                student_id=student_id,
                question_id=question_id,
                selected_option=1,
            )
        )
        await seed.commit()


async def _another_student(db, course) -> UUID:  # noqa: ANN001
    _, factory, created = db
    async with factory() as seed:
        user = User(name="Classmate", role="student", email=f"{uuid4().hex}@t.test")
        seed.add(user)
        await seed.flush()
        created["user"].append(user.user_id)
        student = Student(
            user_id=user.user_id,
            course_id=course.id,
            consent_status="granted",
            enrolled_at=datetime.now(UTC).date(),
        )
        seed.add(student)
        await seed.commit()
        return student.student_id


async def _student_id(db, user_id: UUID = STUDENT_ID) -> UUID:  # noqa: ANN001
    from sqlalchemy import select

    _, factory, _ = db
    async with factory() as read:
        return (
            await read.execute(select(Student.student_id).where(Student.user_id == user_id))
        ).scalar_one()


# -- the list ---------------------------------------------------------------------------


async def test_a_lecturer_lists_their_own_sessions_and_not_another_lecturers(db, app) -> None:  # noqa: ANN001
    client = db[0]
    _, mine, _, theirs = await _two_lecturers_sessions(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    listed = _ids(client.get("/api/v1/sessions"))

    assert mine["id"] in listed
    assert theirs["id"] not in listed


async def test_an_admin_lists_every_session(db, app) -> None:  # noqa: ANN001
    client = db[0]
    _, mine, _, theirs = await _two_lecturers_sessions(db, app)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    listed = _ids(client.get("/api/v1/sessions", params={"limit": 200}))

    assert {mine["id"], theirs["id"]} <= listed


async def test_a_student_lists_only_the_sessions_of_their_course(db, app) -> None:  # noqa: ANN001
    client, factory, _ = db
    course, mine, _, theirs = await _two_lecturers_sessions(db, app)
    await enrol(factory, course)
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    listed = _ids(client.get("/api/v1/sessions"))

    assert mine["id"] in listed
    assert theirs["id"] not in listed


async def test_the_list_is_paginated_and_counts_everything_visible(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    for n in range(3):
        create_session(client, course, f"Week {n}")

    first = client.get("/api/v1/sessions", params={"limit": 2}).json()
    rest = client.get("/api/v1/sessions", params={"limit": 2, "offset": 2}).json()

    assert (first["limit"], len(first["items"])) == (2, 2)
    assert first["total"] == rest["total"] >= 3
    # No session is on both pages.
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in rest["items"]}


# -- one session ------------------------------------------------------------------------


async def test_a_session_is_read_by_its_lecturer_and_missing_for_another(db, app) -> None:  # noqa: ANN001
    client = db[0]
    _, mine, _, theirs = await _two_lecturers_sessions(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    read = client.get(f"/api/v1/sessions/{mine['id']}")
    hidden = client.get(f"/api/v1/sessions/{theirs['id']}")
    missing = client.get(f"/api/v1/sessions/{uuid4()}")

    assert read.status_code == 200 and read.json()["title"] == mine["title"]
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["message"] == missing.json()["error"]["message"]


async def test_a_student_reads_a_session_of_their_course_and_not_another(db, app) -> None:  # noqa: ANN001
    client, factory, _ = db
    course, mine, _, theirs = await _two_lecturers_sessions(db, app)
    await enrol(factory, course)
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    assert client.get(f"/api/v1/sessions/{mine['id']}").status_code == 200
    assert client.get(f"/api/v1/sessions/{theirs['id']}").status_code == 404


# -- responses --------------------------------------------------------------------------


async def test_the_lecturer_reads_every_response_and_a_student_only_their_own(db, app) -> None:  # noqa: ANN001
    client, factory, _ = db
    course, mine, _, _ = await _two_lecturers_sessions(db, app)
    await enrol(factory, course)
    question = await add_question(db, course, LECTURER_ID, status="delivered")
    me = await _student_id(db)
    classmate = await _another_student(db, course)
    await _answer(db, mine["id"], me, question)
    await _answer(db, mine["id"], classmate, question)
    path = f"/api/v1/sessions/{mine['id']}/responses"

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    everyone = client.get(path).json()
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    own = client.get(path).json()

    assert everyone["total"] == 2
    assert {item["student_id"] for item in everyone["items"]} == {str(me), str(classmate)}
    assert own["total"] == 1
    assert [item["student_id"] for item in own["items"]] == [str(me)]


async def test_responses_of_a_session_someone_cannot_see_are_missing(db, app) -> None:  # noqa: ANN001
    client = db[0]
    _, _, _, theirs = await _two_lecturers_sessions(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert client.get(f"/api/v1/sessions/{theirs['id']}/responses").status_code == 404
