"""Session lifecycle routes and socket membership, against a real database.

Owner: General CS, Phase 3. The timing of delivery and answers is covered
without a database in test_classroom.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

from app.api.deps import Principal, get_principal
from app.auth.store import (
    ADMIN_ID,
    LECTURER_ID,
    STUDENT_ID,
    dev_user_records,
    get_consent_repository,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.realtime.classroom import classroom
from app.schemas.identity import ConsentType, Role

from .database_support import require_database
from .dev_credentials import LECTURER_PASSWORD, STUDENT_PASSWORD


@pytest.fixture
async def db(app):
    """A TestClient and a session factory sharing one engine with get_db."""
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async with factory() as seed:
        # The development accounts sign in from memory but own rows by id.
        await seed.execute(
            insert(User)
            .values(
                [
                    {
                        "user_id": r.id,
                        "name": r.full_name,
                        "email": r.email,
                        "role": r.role.value,
                        "password_hash": r.password_hash,
                    }
                    for r in dev_user_records()
                ]
            )
            .on_conflict_do_nothing()
        )
        await seed.commit()

    app.dependency_overrides[get_db] = _get_db
    created: dict[str, list[UUID]] = {"course": [], "material": [], "user": []}
    with TestClient(app) as client:
        yield client, factory, created
    app.dependency_overrides.clear()

    async with factory() as cleanup:
        courses, materials = created["course"], created["material"]
        await cleanup.execute(
            delete(StudentResponse).where(
                StudentResponse.question_id.in_(
                    select(Question.question_id).where(Question.source_material_id.in_(materials))
                )
            )
        )
        await cleanup.execute(delete(Question).where(Question.source_material_id.in_(materials)))
        await cleanup.execute(delete(SessionModel).where(SessionModel.course_id.in_(courses)))
        await cleanup.execute(delete(Material).where(Material.id.in_(materials)))
        await cleanup.execute(delete(Student).where(Student.course_id.in_(courses)))
        await cleanup.execute(delete(Course).where(Course.id.in_(courses)))
        await cleanup.execute(delete(User).where(User.user_id.in_(created["user"])))
        await cleanup.commit()
    await engine.dispose()


def _as(app, user_id: UUID, role: Role) -> None:
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=user_id, role=role, email=f"{role.value}@clip.example.com"
    )
    get_consent_repository(get_settings()).record(user_id, ConsentType.TERMS, True)


async def _course(factory, created) -> Course:
    async with factory() as seed:
        course = Course(code=f"T{uuid4().hex[:8]}", name="Live Test Course")
        seed.add(course)
        await seed.commit()
    created["course"].append(course.id)
    return course


async def _lecturer(factory, created) -> UUID:
    user_id = uuid4()
    async with factory() as seed:
        seed.add(
            User(user_id=user_id, name="Other", role="lecturer", email=f"{user_id.hex}@t.test")
        )
        await seed.commit()
    created["user"].append(user_id)
    return user_id


async def _question(
    db,
    course: Course,
    uploaded_by: UUID,
    status: str = "staged",
    course_id: bool = True,
    question_type: str = "mcq",
    options: list[str] | None = None,
) -> UUID:
    _, factory, created = db
    async with factory() as seed:
        material = Material(
            course_id=course.id if course_id else None,
            filename="week1.pdf",
            content_type="application/pdf",
            size_bytes=10,
            status="completed",
            uploaded_by_user_id=uploaded_by,
        )
        seed.add(material)
        await seed.flush()
        question = Question(
            source_material_id=material.id,
            question_text="Which planet is largest?",
            question_type=question_type,
            status=status,
            options=["Mars", "Jupiter", "Venus"] if options is None else options,
            correct_option=1,
            source_slide=3,
        )
        seed.add(question)
        await seed.commit()
    created["material"].append(material.id)
    return question.question_id


async def _enrol(factory, course: Course, user_id: UUID = STUDENT_ID) -> None:
    """Move the student onto this course. An upsert, because startup enrols
    the development student on the development course at the same time."""
    async with factory() as seed:
        await seed.execute(
            insert(Student)
            .values(
                user_id=user_id,
                course_id=course.id,
                consent_status="granted",
                enrolled_at=date(2026, 9, 1),
            )
            .on_conflict_do_update(index_elements=[Student.user_id], set_={"course_id": course.id})
        )
        await seed.commit()


def _create(client: TestClient, course: Course, title: str = "Week 1") -> dict:
    response = client.post("/api/v1/sessions", json={"course_code": course.code, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _token(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


# -- creating ---------------------------------------------------------------


async def test_a_lecturer_prepares_a_session_for_a_course(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)

    session = _create(client, course, "  Week 1: Planets  ")

    assert session["status"] == "prepared"
    assert session["course_code"] == course.code
    assert session["title"] == "Week 1: Planets"
    assert session["lecturer_id"] == str(LECTURER_ID)
    assert (session["questions_delivered"], session["ended_at"]) == (0, None)


async def test_a_session_needs_a_known_course_and_a_title(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)

    unknown = client.post("/api/v1/sessions", json={"course_code": "NOPE999", "title": "x"})
    blank = client.post("/api/v1/sessions", json={"course_code": course.code, "title": "  "})
    long = client.post("/api/v1/sessions", json={"course_code": course.code, "title": "x" * 201})

    assert unknown.status_code == 404
    assert blank.status_code == 422
    assert long.status_code == 422


async def test_students_cannot_run_sessions(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, STUDENT_ID, Role.STUDENT)

    response = client.post("/api/v1/sessions", json={"course_code": course.code, "title": "x"})

    assert response.status_code == 403
    assert client.post(f"/api/v1/sessions/{uuid4()}/start").status_code == 403
    assert client.post(f"/api/v1/sessions/{uuid4()}/end").status_code == 403


# -- starting ---------------------------------------------------------------


async def test_a_session_will_not_start_without_a_staged_question(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID, status="approved")
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    response = client.post(f"/api/v1/sessions/{session['id']}/start")

    assert response.status_code == 409
    assert "Stage" in response.json()["error"]["message"]


async def test_another_lecturers_staged_question_does_not_count(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    other = await _lecturer(factory, created)
    await _question(db, course, other)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 409


async def test_a_question_for_another_course_does_not_count(db, app) -> None:
    client, factory, created = db
    course, elsewhere = await _course(factory, created), await _course(factory, created)
    await _question(db, elsewhere, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 409


async def test_a_staged_question_starts_the_session(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    response = client.post(f"/api/v1/sessions/{session['id']}/start")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    again = client.post(f"/api/v1/sessions/{session['id']}/start")
    assert again.status_code == 409


async def test_only_the_lecturer_who_runs_it_or_an_admin_may_start_it(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    _as(app, await _lecturer(factory, created), Role.LECTURER)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 404
    _as(app, ADMIN_ID, Role.ADMIN)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200


# -- listing deliverable questions -----------------------------------------


async def test_owner_can_list_deliverable_questions(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)

    question_id = await _question(
        db,
        course,
        LECTURER_ID,
    )

    _as(
        app,
        LECTURER_ID,
        Role.LECTURER,
    )

    session = _create(
        client,
        course,
    )

    base = f"/api/v1/sessions/{session['id']}"

    assert client.post(f"{base}/start").status_code == 200

    response = client.get(f"{base}/questions")

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(question_id)
    assert body["items"][0]["prompt"] == "Which planet is largest?"
    assert body["items"][0]["options"] == [
        "Mars",
        "Jupiter",
        "Venus",
    ]

    client.post(f"{base}/end")


async def test_non_owner_cannot_list_deliverable_questions(
    db,
    app,
) -> None:
    client, factory, created = db
    course = await _course(factory, created)

    await _question(
        db,
        course,
        LECTURER_ID,
    )

    _as(
        app,
        LECTURER_ID,
        Role.LECTURER,
    )

    session = _create(
        client,
        course,
    )

    base = f"/api/v1/sessions/{session['id']}"

    assert client.post(f"{base}/start").status_code == 200

    other_lecturer = await _lecturer(
        factory,
        created,
    )

    _as(
        app,
        other_lecturer,
        Role.LECTURER,
    )

    response = client.get(f"{base}/questions")

    assert response.status_code == 404


async def test_inactive_session_cannot_list_deliverable_questions(
    db,
    app,
) -> None:
    client, factory, created = db
    course = await _course(factory, created)

    await _question(
        db,
        course,
        LECTURER_ID,
    )

    _as(
        app,
        LECTURER_ID,
        Role.LECTURER,
    )

    session = _create(
        client,
        course,
    )

    response = client.get(f"/api/v1/sessions/{session['id']}/questions")

    assert response.status_code == 409


async def test_deliverable_question_list_excludes_wrong_course_and_broken_mcq(
    db,
    app,
) -> None:
    client, factory, created = db

    course = await _course(
        factory,
        created,
    )

    other_course = await _course(
        factory,
        created,
    )

    valid_question = await _question(
        db,
        course,
        LECTURER_ID,
    )

    wrong_course_question = await _question(
        db,
        other_course,
        LECTURER_ID,
    )

    broken_mcq = await _question(
        db,
        course,
        LECTURER_ID,
        options=[],
    )

    _as(
        app,
        LECTURER_ID,
        Role.LECTURER,
    )

    session = _create(
        client,
        course,
    )

    base = f"/api/v1/sessions/{session['id']}"

    assert client.post(f"{base}/start").status_code == 200

    response = client.get(f"{base}/questions")

    assert response.status_code == 200, response.text

    body = response.json()

    returned_ids = {item["id"] for item in body["items"]}

    assert str(valid_question) in returned_ids
    assert str(wrong_course_question) not in returned_ids
    assert str(broken_mcq) not in returned_ids
    assert body["total"] == 1

    client.post(f"{base}/end")


# -- ending -----------------------------------------------------------------


async def test_ending_a_running_session(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")

    ended = client.post(f"/api/v1/sessions/{session['id']}/end")

    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    assert ended.json()["ended_at"] is not None
    assert client.post(f"/api/v1/sessions/{session['id']}/end").status_code == 409
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 409


async def test_ending_a_session_that_never_started_cancels_it(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    response = client.post(f"/api/v1/sessions/{session['id']}/end")

    assert response.json()["status"] == "cancelled"


# -- delivering -------------------------------------------------------------


async def test_the_lecturer_delivers_a_staged_question(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    question_id = await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")

    response = client.post(f"/api/v1/sessions/{session['id']}/questions/{question_id}:deliver")

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "delivered", "question_id": str(question_id)}
    async with factory() as check:
        question = await check.get(Question, question_id)
        assert question is not None
        assert (question.status, question.session_id) == ("delivered", UUID(session["id"]))
    ended = client.post(f"/api/v1/sessions/{session['id']}/end").json()
    assert ended["questions_delivered"] == 1


async def test_a_material_for_no_course_is_deliverable_in_any_of_its_uploaders_sessions(
    db, app
) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    question_id = await _question(db, course, LECTURER_ID, course_id=False)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")

    response = client.post(f"/api/v1/sessions/{session['id']}/questions/{question_id}:deliver")

    assert response.status_code == 202
    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_delivery_is_refused_while_a_question_is_open(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    first = await _question(db, course, LECTURER_ID)
    second = await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")

    client.post(f"/api/v1/sessions/{session['id']}/questions/{first}:deliver")
    response = client.post(f"/api/v1/sessions/{session['id']}/questions/{second}:deliver")

    assert response.status_code == 409
    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_only_a_staged_question_can_be_delivered(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    draft = await _question(db, course, LECTURER_ID, status="approved")
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")

    response = client.post(f"/api/v1/sessions/{session['id']}/questions/{draft}:deliver")

    assert response.status_code == 404
    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_nothing_is_delivered_before_the_session_starts(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    question_id = await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    response = client.post(f"/api/v1/sessions/{session['id']}/questions/{question_id}:deliver")

    assert response.status_code == 409


# -- the socket -------------------------------------------------------------


def _refused_with(client: TestClient, token: str, session_id: str) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "auth", "data": {"token": token, "session_id": session_id}})
            ws.receive_json()
            ws.receive_json()
    return exc.value.code


async def test_an_enrolled_student_joins_and_is_told_the_state(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        ready, state = ws.receive_json(), ws.receive_json()

    assert (ready["type"], ready["data"]["session_id"]) == ("ready", session["id"])
    assert UUID(ready["data"]["stream_id"])
    assert (state["type"], state["seq"], state["data"]["status"]) == (
        "session.state",
        0,
        "prepared",
    )


async def test_a_valid_token_does_not_open_a_session_that_does_not_exist(db, app) -> None:
    client, _, _ = db
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    assert _refused_with(client, token, str(uuid4())) == 4003


async def test_a_student_on_another_course_is_refused(db, app) -> None:
    client, factory, created = db
    course, other = await _course(factory, created), await _course(factory, created)
    await _enrol(factory, other)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    assert _refused_with(client, token, session["id"]) == 4003


async def test_a_session_that_has_ended_cannot_be_joined(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/end")
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    assert _refused_with(client, token, session["id"]) == 4003


async def test_a_lecturer_cannot_join_another_lecturers_session(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, await _lecturer(factory, created), Role.LECTURER)
    session = _create(client, course)
    token = _token(client, "lecturer@clip.example.com", LECTURER_PASSWORD)

    assert _refused_with(client, token, session["id"]) == 4003


async def test_a_question_goes_out_and_the_answer_comes_back(db, app) -> None:
    """The whole loop: start, join, deliver, answer, receipt, end."""
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    question_id = await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json()["data"]["status"] == "active"

        delivered = client.post(f"/api/v1/sessions/{session['id']}/questions/{question_id}:deliver")
        assert delivered.status_code == 202
        question = ws.receive_json()
        assert question["type"] == "question.delivered"
        assert question["data"]["options"] == ["Mars", "Jupiter", "Venus"]
        assert "correct_option" not in question["data"]

        ws.send_json(
            {
                "type": "answer.submit",
                "data": {
                    "question_id": str(question_id),
                    "selected_option": 1,
                    "client_elapsed_ms": 4200,
                },
            }
        )
        receipt = ws.receive_json()
        assert (receipt["type"], receipt["seq"], receipt["data"]["accepted"]) == (
            "answer.receipt",
            0,
            True,
        )
        feedback = ws.receive_json()
        assert (feedback["type"], feedback["data"]["correct"]) == ("feedback.result", True)

        client.post(f"/api/v1/sessions/{session['id']}/end")
        closed, ended = ws.receive_json(), ws.receive_json()

    assert (closed["type"], closed["seq"]) == ("question.closed", question["seq"] + 1)
    assert (closed["data"]["respondents"], closed["data"]["eligible"]) == (1, 1)
    assert (ended["type"], ended["data"]["status"]) == ("session.state", "ended")


# -- pausing ----------------------------------------------------------------


async def test_a_running_session_pauses_and_resumes(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    question_id = await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    base = f"/api/v1/sessions/{session['id']}"
    client.post(f"{base}/start")

    paused = client.post(f"{base}/pause")

    assert paused.status_code == 200, paused.text
    assert (paused.json()["status"], paused.json()["paused"]) == ("active", True)
    assert client.post(f"{base}/pause").status_code == 409
    assert client.post(f"{base}/questions/{question_id}:deliver").status_code == 409
    async with factory() as check:
        row = await check.get(SessionModel, UUID(session["id"]))
        assert row is not None and row.paused_at is not None

    resumed = client.post(f"{base}/resume")

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["paused"] is False
    assert client.post(f"{base}/resume").status_code == 409
    assert client.post(f"{base}/questions/{question_id}:deliver").status_code == 202


async def test_only_a_running_session_can_be_paused(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    base = f"/api/v1/sessions/{session['id']}"

    assert client.post(f"{base}/pause").status_code == 409
    assert client.post(f"{base}/resume").status_code == 409
    client.post(f"{base}/start")
    client.post(f"{base}/pause")
    ended = client.post(f"{base}/end")
    assert (ended.status_code, ended.json()["status"], ended.json()["paused"]) == (
        200,
        "ended",
        False,
    )
    assert client.post(f"{base}/resume").status_code == 409


async def test_pausing_is_staff_work_on_their_own_session(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    base = f"/api/v1/sessions/{session['id']}"
    client.post(f"{base}/start")

    _as(app, STUDENT_ID, Role.STUDENT)
    assert client.post(f"{base}/pause").status_code == 403
    _as(app, await _lecturer(factory, created), Role.LECTURER)
    assert client.post(f"{base}/pause").status_code == 404
    _as(app, ADMIN_ID, Role.ADMIN)
    assert client.post(f"{base}/pause").status_code == 200


async def test_a_student_joining_a_paused_session_is_told_it_is_paused(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")
    client.post(f"/api/v1/sessions/{session['id']}/pause")
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        ws.receive_json()
        state = ws.receive_json()

    assert (state["data"]["status"], state["data"]["paused"]) == ("active", True)


async def test_a_prompt_acknowledgement_needs_an_open_prompt(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    await _question(db, course, LECTURER_ID)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)
    ack = {"type": "prompt.ack", "data": {"prompt_id": str(uuid4())}}

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        ws.receive_json()
        ws.receive_json()
        ws.send_json(ack)
        error = ws.receive_json()
        ws.send_json({"type": "ping", "data": {}})
        pong = ws.receive_json()

    assert (error["type"], error["data"]["code"]) == ("error", "PROMPT_NOT_OPEN")
    assert pong["type"] == "pong"
    client.post(f"/api/v1/sessions/{session['id']}/end")


async def test_a_multiple_choice_question_with_no_choices_is_not_delivered(db, app) -> None:
    """Nobody could answer it, so the class is never shown it and it does not
    count towards the staged question a session needs to start."""
    client, factory, created = db
    course = await _course(factory, created)
    broken = await _question(db, course, LECTURER_ID, options=[])
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    base = f"/api/v1/sessions/{session['id']}"

    refused = client.post(f"{base}/start")

    assert refused.status_code == 409, refused.text
    await _question(db, course, LECTURER_ID)
    assert client.post(f"{base}/start").status_code == 200
    assert client.post(f"{base}/questions/{broken}:deliver").status_code == 404
    client.post(f"{base}/end")


async def test_a_free_text_question_is_delivered_without_options(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    question_id = await _question(db, course, LECTURER_ID, question_type="free_text", options=None)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    base = f"/api/v1/sessions/{session['id']}"
    client.post(f"{base}/start")
    token = _token(client, "student@clip.example.com", STUDENT_PASSWORD)

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        ws.receive_json()
        ws.receive_json()
        assert client.post(f"{base}/questions/{question_id}:deliver").status_code == 202
        delivered = ws.receive_json()
        ws.send_json(
            {
                "type": "answer.submit",
                "data": {
                    "question_id": str(question_id),
                    "free_text": "Jupiter is the largest",
                    "client_elapsed_ms": 3000,
                },
            }
        )
        receipt = ws.receive_json()

    assert delivered["data"]["options"] is None
    assert receipt["data"]["accepted"] is True, receipt["data"]
    client.post(f"{base}/end")


# -- engagement and alerts (Cyber 1) ------------------------------------------


async def test_another_lecturer_cannot_read_a_sessions_engagement_or_alerts(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    _as(app, await _lecturer(factory, created), Role.LECTURER)

    for path in ("engagement", "alerts"):
        response = client.get(f"/api/v1/sessions/{session['id']}/{path}")
        assert response.status_code == 404, path


async def test_an_admin_may_read_any_sessions_engagement_and_alerts(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    _as(app, ADMIN_ID, Role.ADMIN)

    for path in ("engagement", "alerts"):
        response = client.get(f"/api/v1/sessions/{session['id']}/{path}")
        assert response.status_code == 200, path


async def test_a_student_is_refused_engagement_and_alerts(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    _as(app, STUDENT_ID, Role.STUDENT)

    for path in ("engagement", "alerts"):
        response = client.get(f"/api/v1/sessions/{session['id']}/{path}")
        assert response.status_code == 403, path


async def test_a_session_this_process_is_not_running_reports_nothing(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)

    assert client.get(f"/api/v1/sessions/{session['id']}/engagement").json() == []
    assert client.get(f"/api/v1/sessions/{session['id']}/alerts").json() == []


async def test_engagement_reports_the_student_id_not_the_user_id(db, app) -> None:
    client, factory, created = db
    course = await _course(factory, created)
    await _enrol(factory, course)
    _as(app, LECTURER_ID, Role.LECTURER)
    session = _create(client, course)
    session_id = UUID(session["id"])
    async with factory() as read:
        student_id = await read.scalar(
            select(Student.student_id).where(Student.user_id == STUDENT_ID)
        )

    live = classroom.activate(session_id, paused=True)
    # Two questions shown and both answered.
    for _ in range(2):
        live.attention.score({STUDENT_ID}, {STUDENT_ID}, {}, datetime.now(UTC))
    try:
        [scored] = client.get(f"/api/v1/sessions/{session_id}/engagement").json()
    finally:
        classroom._live.pop(session_id, None)

    assert scored["student_id"] == str(student_id)
    assert scored["student_id"] != str(STUDENT_ID)
    assert (scored["status"], scored["signals_available"]) == ("engaged", ["attempt_rate"])
