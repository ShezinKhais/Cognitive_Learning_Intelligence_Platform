"""End-to-end Phase 3 live session tests: REST lifecycle plus the WebSocket
answer/engagement/prompt path.

Uses the fixed dev identities (LECTURER_ID, STUDENT_ID) rather than
arbitrary UUIDs: development authentication (app.auth.store) never touches
the `user` table, so a WebSocket connection can only ever authenticate as
one of those three accounts, same as test_ws.py. Rows for them are seeded
into the real `user` table anyway because Session/Student's foreign keys
require it, following scripts/seed.py's idempotent insert-if-absent style.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.user import User

from .dev_credentials import LECTURER_PASSWORD, STUDENT_PASSWORD

FAST_SETTINGS = Settings(
    checkpoint_response_window_seconds=1,
    checkpoint_interval_seconds=3600,
    comprehension_alert_min_respondents=1,
    comprehension_alert_threshold=0.99,
    dynamic_prompt_max_per_student=3,
)


@pytest.fixture
async def db_client(app):
    """A TestClient plus a session_factory sharing one engine with get_db.

    Same technique test_question_review.py's db_client uses, for the same
    reason: the WebSocket runs on its own loop inside TestClient, and a
    session tied to a different loop's engine breaks mid-request.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no database reachable ({type(exc).__name__})")

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: FAST_SETTINGS

    with TestClient(app) as test_client:
        yield test_client, session_factory

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_settings, None)


async def _ensure_dev_users(session_factory) -> None:
    async with session_factory() as db:
        for user_id, name, role, email in (
            (LECTURER_ID, "Dev Lecturer", "lecturer", "lecturer@clip.example.com"),
            (STUDENT_ID, "Dev Student", "student", "student@clip.example.com"),
        ):
            existing = await db.get(User, user_id)
            if existing is None:
                db.add(User(user_id=user_id, name=name, role=role, email=email))
        await db.commit()


async def _seed_session_with_staged_mcq(session_factory) -> tuple:
    """One course (student enrolled), one prepared session, one staged MCQ.

    Returns (course_id, session_id, question_id).
    """
    await _ensure_dev_users(session_factory)

    async with session_factory() as db:
        course = Course(code=f"C{uuid4().hex[:8]}", name="Phase 3 Test Course")
        db.add(course)
        await db.flush()

        db.add(
            Student(
                user_id=STUDENT_ID,
                course_id=course.id,
                consent_status="granted",
                enrolled_at=date.today(),
            )
        )

        material = Material(
            course_id=course.id,
            filename="lecture.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            status="completed",
        )
        db.add(material)
        await db.flush()

        now = datetime.now(UTC)
        session_row = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=course.id,
            title="Live Session",
            start_time=now,
            end_time=now + timedelta(hours=1),
            mode="online",
            status="prepared",
        )
        db.add(session_row)
        await db.flush()

        question = Question(
            source_material_id=material.id,
            question_text="What is the capital of France?",
            session_id=session_row.session_id,
            question_type="mcq",
            status="staged",
            difficulty="medium",
            options=["Paris", "Lyon", "Marseille"],
            correct_option=0,
            topic="Geography",
        )
        db.add(question)
        await db.commit()

        return course.id, session_row.session_id, question.question_id


async def _cleanup(session_factory, course_id, session_id) -> None:
    async with session_factory() as db:
        for table in (
            "missed_response",
            "delivered_question",
            "student_response",
            "engagement_record",
            "dynamic_prompt",
            "session_participant",
            "question",
        ):
            await db.execute(
                text(f"delete from {table} where session_id = :sid"), {"sid": session_id}
            )
        await db.execute(text("delete from session where session_id = :sid"), {"sid": session_id})
        await db.execute(text("delete from student where course_id = :cid"), {"cid": course_id})
        # source_material.course_id references course; skipping this left the
        # course delete below failing on a foreign key violation, which rolled
        # back the whole cleanup transaction silently and leaked every row
        # (including the unique student_id) into the next test.
        await db.execute(
            text("delete from source_material where course_id = :cid"), {"cid": course_id}
        )
        await db.execute(text("delete from course where id = :cid"), {"cid": course_id})
        await db.commit()


def _login(client, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _grant_terms(client, token: str) -> None:
    response = client.post(
        "/api/v1/auth/consent",
        headers={"Authorization": f"Bearer {token}"},
        json={"consent_type": "terms", "granted": True},
    )
    assert response.status_code == 201


async def test_start_session_rejects_a_session_with_no_staged_question(db_client):
    client, session_factory = db_client
    await _ensure_dev_users(session_factory)

    async with session_factory() as db:
        course = Course(code=f"C{uuid4().hex[:8]}", name="Empty Course")
        db.add(course)
        await db.flush()
        now = datetime.now(UTC)
        session_row = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=course.id,
            title="No Questions Yet",
            start_time=now,
            end_time=now,
            mode="online",
            status="prepared",
        )
        db.add(session_row)
        await db.commit()
        course_id, session_id = course.id, session_row.session_id

    try:
        token = _login(client, "lecturer@clip.example.com", LECTURER_PASSWORD)
        _grant_terms(client, token)

        response = client.post(
            f"/api/v1/sessions/{session_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(session_factory, course_id, session_id)


async def test_full_live_session_cycle(db_client):
    client, session_factory = db_client
    course_id, session_id, question_id = await _seed_session_with_staged_mcq(session_factory)

    try:
        lecturer_token = _login(client, "lecturer@clip.example.com", LECTURER_PASSWORD)
        student_token = _login(client, "student@clip.example.com", STUDENT_PASSWORD)
        _grant_terms(client, lecturer_token)
        _grant_terms(client, student_token)
        lecturer_headers = {"Authorization": f"Bearer {lecturer_token}"}

        start_resp = client.post(f"/api/v1/sessions/{session_id}/start", headers=lecturer_headers)
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "active"

        with client.websocket_connect("/ws/session") as ws:
            ws.send_json(
                {
                    "type": "auth",
                    "data": {"token": student_token, "session_id": str(session_id)},
                }
            )
            ready = ws.receive_json()
            assert ready["type"] == "ready"

            state = ws.receive_json()
            assert state["type"] == "session.state"
            assert state["data"]["status"] == "active"

            deliver_resp = client.post(
                f"/api/v1/sessions/{session_id}/questions/{question_id}:deliver",
                headers=lecturer_headers,
            )
            assert deliver_resp.status_code == 202

            delivered = ws.receive_json()
            assert delivered["type"] == "question.delivered"
            assert delivered["data"]["question_id"] == str(question_id)
            assert delivered["data"]["options"] == ["Paris", "Lyon", "Marseille"]

            ws.send_json(
                {
                    "type": "answer.submit",
                    "data": {
                        "question_id": str(question_id),
                        "selected_option": 0,
                        "client_elapsed_ms": 1200,
                    },
                }
            )

            receipt = ws.receive_json()
            assert receipt["type"] == "answer.receipt"
            assert receipt["data"]["accepted"] is True

            feedback = ws.receive_json()
            assert feedback["type"] == "feedback.result"
            assert feedback["data"]["correct"] is True
            assert feedback["data"]["source_slide"] is None

            engagement_update = ws.receive_json()
            assert engagement_update["type"] == "engagement.update"
            assert engagement_update["data"]["status"] == "engaged"

            closed = ws.receive_json()
            assert closed["type"] == "question.closed"
            assert closed["data"]["reason"] == "window_elapsed"
            assert closed["data"]["respondents"] == 1
            assert closed["data"]["eligible"] == 1

        responses_resp = client.get(
            f"/api/v1/sessions/{session_id}/responses", headers=lecturer_headers
        )
        assert responses_resp.status_code == 200
        assert responses_resp.json()["total"] == 1
        assert responses_resp.json()["items"][0]["is_correct"] is True

        engagement_resp = client.get(
            f"/api/v1/sessions/{session_id}/engagement", headers=lecturer_headers
        )
        assert engagement_resp.status_code == 200
        assert engagement_resp.json()[0]["status"] == "engaged"

        end_resp = client.post(f"/api/v1/sessions/{session_id}/end", headers=lecturer_headers)
        assert end_resp.status_code == 200
        assert end_resp.json()["status"] == "ended"
    finally:
        await _cleanup(session_factory, course_id, session_id)


async def test_a_student_not_enrolled_cannot_join_the_session(db_client):
    client, session_factory = db_client
    course_id, session_id, _question_id = await _seed_session_with_staged_mcq(session_factory)

    # Unenrol the student to prove membership, not just a valid token, gates
    # access.
    async with session_factory() as db:
        result = await db.execute(select(Student).where(Student.user_id == STUDENT_ID))
        student = result.scalar_one()
        await db.delete(student)
        await db.commit()

    try:
        student_token = _login(client, "student@clip.example.com", STUDENT_PASSWORD)
        _grant_terms(client, student_token)

        with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
            with client.websocket_connect("/ws/session") as ws:
                ws.send_json(
                    {
                        "type": "auth",
                        "data": {"token": student_token, "session_id": str(session_id)},
                    }
                )
                ws.receive_json()

        assert exc.value.code == 4003
    finally:
        await _cleanup(session_factory, course_id, session_id)


async def test_manual_delivery_closes_the_previous_open_question_early(db_client):
    """The lecturer triggering a second question early closes the first with
    LECTURER_CLOSED rather than leaving two questions open at once."""
    client, session_factory = db_client
    course_id, session_id, first_question_id = await _seed_session_with_staged_mcq(session_factory)

    async with session_factory() as db:
        first_question = await db.get(Question, first_question_id)
        second = Question(
            source_material_id=first_question.source_material_id,
            question_text="What is 2 + 2?",
            session_id=session_id,
            question_type="mcq",
            status="staged",
            difficulty="easy",
            options=["3", "4", "5"],
            correct_option=1,
        )
        db.add(second)
        await db.commit()
        second_question_id = second.question_id

    try:
        lecturer_token = _login(client, "lecturer@clip.example.com", LECTURER_PASSWORD)
        _grant_terms(client, lecturer_token)
        lecturer_headers = {"Authorization": f"Bearer {lecturer_token}"}

        client.post(f"/api/v1/sessions/{session_id}/start", headers=lecturer_headers)

        first = client.post(
            f"/api/v1/sessions/{session_id}/questions/{first_question_id}:deliver",
            headers=lecturer_headers,
        )
        assert first.status_code == 202

        second_resp = client.post(
            f"/api/v1/sessions/{session_id}/questions/{second_question_id}:deliver",
            headers=lecturer_headers,
        )
        assert second_resp.status_code == 202

        # Let the second question's own window elapse so both timers have
        # finished before the database is inspected.
        await asyncio.sleep(1.5)

        async with session_factory() as db:
            from app.models.delivered_question import DeliveredQuestion

            result = await db.execute(
                select(DeliveredQuestion)
                .where(DeliveredQuestion.session_id == session_id)
                .order_by(DeliveredQuestion.delivered_at)
            )
            deliveries = list(result.scalars().all())

        assert len(deliveries) == 2
        assert deliveries[0].question_id == first_question_id
        assert deliveries[0].close_reason == "lecturer_closed"
        assert deliveries[1].question_id == second_question_id
        assert deliveries[1].close_reason == "window_elapsed"
    finally:
        await _cleanup(session_factory, course_id, session_id)
