"""Integration tests for the Teams meeting-event webhook and the content-
readiness gate it and the REST start route share.

Owners: General CS (event handling), BBIS (persistence), AI 1 (readiness),
Cyber 1 (signature enforcement).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.core.config import get_settings
from app.core.database import get_db
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.user import User

from .dev_credentials import LECTURER_PASSWORD


@pytest.fixture
async def db_client(app):
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

    with TestClient(app) as test_client:
        yield test_client, session_factory

    app.dependency_overrides.pop(get_db, None)


async def _ensure_dev_users(session_factory) -> None:
    async with session_factory() as db:
        for user_id, name, role, email in (
            (LECTURER_ID, "Dev Lecturer", "lecturer", "lecturer@clip.example.com"),
            (STUDENT_ID, "Dev Student", "student", "student@clip.example.com"),
        ):
            if await db.get(User, user_id) is None:
                db.add(User(user_id=user_id, name=name, role=role, email=email))
        await db.commit()


async def _seed_course_with_enrolled_student(session_factory) -> tuple:
    """A course with the dev student enrolled, no material or session yet.

    Returns course.
    """
    await _ensure_dev_users(session_factory)
    async with session_factory() as db:
        course = Course(code=f"C{uuid4().hex[:8]}", name="Teams Test Course")
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
        await db.commit()
        return course


async def _cleanup(session_factory, course_id) -> None:
    async with session_factory() as db:
        session_ids = (
            (
                await db.execute(
                    text("select session_id from session where course_id = :cid"),
                    {"cid": course_id},
                )
            )
            .scalars()
            .all()
        )
        for sid in session_ids:
            for table in (
                "missed_response",
                "delivered_question",
                "student_response",
                "engagement_record",
                "dynamic_prompt",
                "session_participant",
                "roster_sync_event",
                "teams_meeting",
                "question",
            ):
                await db.execute(text(f"delete from {table} where session_id = :sid"), {"sid": sid})
        await db.execute(text("delete from session where course_id = :cid"), {"cid": course_id})
        await db.execute(text("delete from student where course_id = :cid"), {"cid": course_id})
        await db.execute(
            text("delete from source_material where course_id = :cid"), {"cid": course_id}
        )
        await db.execute(text("delete from course where id = :cid"), {"cid": course_id})
        await db.commit()


def _event(**overrides) -> dict:
    body = {
        "event": "meeting.started",
        "teams_meeting_id": f"meeting-{uuid4().hex[:12]}",
        "tenant_id": "tenant-1",
        "course_code": "UNSET",
        "title": "Week 3 Lecture",
        "organizer_teams_user_id": "teams-organizer-1",
        "organizer_email": "lecturer@clip.example.com",
        "participants": [],
    }
    body.update(overrides)
    return body


async def test_unknown_course_code_is_ignored_not_created(db_client):
    client, _session_factory = db_client
    response = client.post("/api/v1/teams/events", json=_event(course_code="NOPE-9999"))
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_meeting_started_is_blocked_without_ready_content(db_client):
    client, session_factory = db_client
    course = await _seed_course_with_enrolled_student(session_factory)
    try:
        response = client.post("/api/v1/teams/events", json=_event(course_code=course.code))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "blocked"
        assert body["session_id"] is not None
        assert "material" in body["reason"].lower() or "question" in body["reason"].lower()
    finally:
        await _cleanup(session_factory, course.id)


async def test_meeting_started_links_an_existing_prepared_session_and_goes_active(db_client):
    client, session_factory = db_client
    course = await _seed_course_with_enrolled_student(session_factory)

    async with session_factory() as db:
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
        prepared_session = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=course.id,
            title="Prepared ahead of time",
            start_time=now,
            end_time=now + timedelta(hours=1),
            mode="online",
            status="prepared",
        )
        db.add(prepared_session)
        await db.flush()

        question = Question(
            source_material_id=material.id,
            question_text="What is the capital of France?",
            session_id=prepared_session.session_id,
            question_type="mcq",
            status="staged",
            difficulty="medium",
            options=["Paris", "Lyon"],
            correct_option=0,
        )
        db.add(question)
        await db.commit()
        prepared_session_id = prepared_session.session_id

    try:
        teams_meeting_id = f"meeting-{uuid4().hex[:12]}"
        response = client.post(
            "/api/v1/teams/events",
            json=_event(course_code=course.code, teams_meeting_id=teams_meeting_id),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "started"
        # Linked to the session prepared in advance, not a fresh empty one.
        assert body["session_id"] == str(prepared_session_id)

        # A duplicate delivery of the same webhook must not create a second
        # session or re-run readiness.
        replay = client.post(
            "/api/v1/teams/events",
            json=_event(course_code=course.code, teams_meeting_id=teams_meeting_id),
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "already_linked"
        assert replay.json()["session_id"] == str(prepared_session_id)

        ended = client.post(
            "/api/v1/teams/events",
            json=_event(
                event="meeting.ended",
                course_code=course.code,
                teams_meeting_id=teams_meeting_id,
            ),
        )
        assert ended.status_code == 200
        assert ended.json()["status"] == "ended"

        async with session_factory() as db:
            row = await db.get(SessionModel, prepared_session_id)
            assert row.status == "ended"
    finally:
        await _cleanup(session_factory, course.id)


async def test_roster_sync_matches_by_email_and_reports_unmatched(db_client):
    client, session_factory = db_client
    course = await _seed_course_with_enrolled_student(session_factory)

    async with session_factory() as db:
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
        prepared_session = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=course.id,
            title="Prepared",
            start_time=now,
            end_time=now + timedelta(hours=1),
            mode="online",
            status="prepared",
        )
        db.add(prepared_session)
        await db.flush()
        db.add(
            Question(
                source_material_id=material.id,
                question_text="Q1",
                session_id=prepared_session.session_id,
                question_type="mcq",
                status="staged",
                difficulty="easy",
                options=["A", "B"],
                correct_option=0,
            )
        )
        await db.commit()

    try:
        response = client.post(
            "/api/v1/teams/events",
            json=_event(
                course_code=course.code,
                participants=[
                    {
                        "teams_user_id": "teams-student-1",
                        "display_name": "Dev Student",
                        "email": "student@clip.example.com",
                    },
                    {
                        "teams_user_id": "teams-mystery-1",
                        "display_name": "Someone Not Enrolled",
                        "email": "nobody@clip.example.com",
                    },
                ],
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "started"
        assert body["roster"]["matched"] == 1
        assert body["roster"]["unmatched"] == 1
        assert "Someone Not Enrolled" in body["roster"]["unmatched_names"]
    finally:
        await _cleanup(session_factory, course.id)


async def test_meeting_started_ignores_an_unknown_organizer(db_client):
    client, session_factory = db_client
    course = await _seed_course_with_enrolled_student(session_factory)
    try:
        response = client.post(
            "/api/v1/teams/events",
            json=_event(course_code=course.code, organizer_email="not-a-lecturer@clip.example.com"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
    finally:
        await _cleanup(session_factory, course.id)


async def test_session_readiness_route_matches_the_gate(db_client):
    """GET /sessions/{id}/readiness reports the same block the webhook and
    the manual start route would hit."""
    client, session_factory = db_client
    course = await _seed_course_with_enrolled_student(session_factory)

    async with session_factory() as db:
        now = datetime.now(UTC)
        session_row = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=course.id,
            title="No content yet",
            start_time=now,
            end_time=now,
            mode="online",
            status="prepared",
        )
        db.add(session_row)
        await db.commit()
        session_id = session_row.session_id

    try:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.post(
            "/api/v1/auth/consent",
            headers=headers,
            json={"consent_type": "terms", "granted": True},
        )

        response = client.get(f"/api/v1/sessions/{session_id}/readiness", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is False
        assert body["materials_completed"] == 0
        assert body["approved_questions"] == 0
    finally:
        await _cleanup(session_factory, course.id)
