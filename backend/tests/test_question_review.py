"""Tests for the lecturer question-review interface.

Owner: Cyber 2, Phase 2. Covers:
  - review_question / bulk_review_questions actually mutating rows
  - ownership enforcement: a lecturer can only act on questions from
    sessions they are the instructor of; admins bypass this
  - the not-found vs forbidden distinction for a question that doesn't
    exist at all, vs one that exists but belongs to someone else

Uses a fixture that overrides both get_db and get_principal onto the same
per-test engine, the same technique test_admin_routes.py's DB tests use and
for the same reason: TestClient drives the app on its own event loop, and a
session tied to a different loop's engine breaks mid-request. Sharing the
engine across the override and the seed data means there's no cross-loop or
cross-transaction-visibility question at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import Principal, get_principal
from app.core.config import get_settings
from app.core.database import get_db
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.identity import Role


@pytest.fixture
async def db_client(app):
    """A TestClient plus a session_factory sharing one engine with get_db."""
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

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


def _as(app, user_id: UUID, role: Role, email: str):
    def _principal() -> Principal:
        return Principal(user_id=user_id, role=role, email=email)

    app.dependency_overrides[get_principal] = _principal


async def _seed_question(
    session_factory,
    *,
    instructor_id: UUID,
    status: str = "draft",
) -> tuple[UUID, UUID]:
    """Creates a course, session, material and one question. Returns
    (material_id, question_id)."""
    async with session_factory() as seed:
        course = Course(code=f"C{uuid4().hex[:8]}", name="Test Course")
        seed.add(course)
        await seed.flush()

        lecturer = User(
            user_id=instructor_id,
            name="Seed Lecturer",
            role="lecturer",
            email=f"{uuid4().hex[:8]}@uni.test",
        )
        seed.add(lecturer)

        material = Material(
            course_id=course.id,
            filename="lecture.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            status="completed",
        )
        seed.add(material)
        await seed.flush()

        now = datetime.now(UTC)
        db_session = SessionModel(
            instructor_id=instructor_id,
            course_id=course.id,
            start_time=now,
            end_time=now + timedelta(hours=1),
            mode="in_person",
            status="prepared",
        )
        seed.add(db_session)
        await seed.flush()

        question = Question(
            source_material_id=material.id,
            question_text="What is the capital of France?",
            session_id=db_session.session_id,
            question_type="mcq",
            status=status,
            difficulty="medium",
            options=["Paris", "Lyon", "Marseille"],
            correct_option=0,
        )
        seed.add(question)
        await seed.commit()

        return material.id, question.question_id


async def _cleanup(session_factory, question_id: UUID):
    async with session_factory() as cleanup:
        row = await cleanup.get(Question, question_id)
        if row is None:
            return
        session_id = row.session_id
        material_id = row.source_material_id
        await cleanup.execute(
            text("delete from question where question_id = :qid"), {"qid": question_id}
        )
        session_row = await cleanup.get(SessionModel, session_id)
        instructor_id = session_row.instructor_id if session_row else None
        await cleanup.execute(
            text("delete from session where session_id = :sid"), {"sid": session_id}
        )
        material_row = await cleanup.get(Material, material_id)
        course_id = material_row.course_id if material_row else None
        await cleanup.execute(
            text("delete from source_material where id = :mid"), {"mid": material_id}
        )
        if instructor_id:
            await cleanup.execute(
                text('delete from "user" where user_id = :uid'), {"uid": instructor_id}
            )
        if course_id:
            await cleanup.execute(text("delete from course where id = :cid"), {"cid": course_id})
        await cleanup.commit()


async def test_owning_lecturer_can_approve_a_question(db_client, app):
    test_client, session_factory = db_client
    lecturer_id = uuid4()
    material_id, question_id = await _seed_question(session_factory, instructor_id=lecturer_id)
    try:
        _as(app, lecturer_id, Role.LECTURER, "owner@uni.test")

        resp = test_client.patch(
            f"/api/v1/materials/{material_id}/questions/{question_id}",
            json={"status": "approved"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["id"] == str(question_id)
    finally:
        await _cleanup(session_factory, question_id)
        app.dependency_overrides.pop(get_principal, None)


async def test_owning_lecturer_can_edit_prompt_and_options_on_approve(db_client, app):
    test_client, session_factory = db_client
    lecturer_id = uuid4()
    material_id, question_id = await _seed_question(session_factory, instructor_id=lecturer_id)
    try:
        _as(app, lecturer_id, Role.LECTURER, "owner@uni.test")

        resp = test_client.patch(
            f"/api/v1/materials/{material_id}/questions/{question_id}",
            json={
                "status": "approved",
                "prompt": "What is the capital city of France?",
                "options": ["Paris", "Nice", "Marseille"],
                "correct_option": 0,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt"] == "What is the capital city of France?"
        assert body["options"] == ["Paris", "Nice", "Marseille"]
    finally:
        await _cleanup(session_factory, question_id)
        app.dependency_overrides.pop(get_principal, None)


async def test_non_owning_lecturer_gets_403(db_client, app):
    test_client, session_factory = db_client
    owner_id = uuid4()
    other_lecturer_id = uuid4()
    material_id, question_id = await _seed_question(session_factory, instructor_id=owner_id)
    try:
        _as(app, other_lecturer_id, Role.LECTURER, "notowner@uni.test")

        resp = test_client.patch(
            f"/api/v1/materials/{material_id}/questions/{question_id}",
            json={"status": "approved"},
        )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
    finally:
        await _cleanup(session_factory, question_id)
        app.dependency_overrides.pop(get_principal, None)


async def test_admin_can_review_any_lecturers_question(db_client, app):
    test_client, session_factory = db_client
    owner_id = uuid4()
    admin_id = uuid4()
    material_id, question_id = await _seed_question(session_factory, instructor_id=owner_id)
    try:
        # The admin doing the reviewing must itself exist as a User row --
        # reviewed_by is a real FK, not just an id carried in the token.
        async with session_factory() as seed:
            seed.add(
                User(
                    user_id=admin_id,
                    name="Seed Admin",
                    role="admin",
                    email=f"{uuid4().hex[:8]}@uni.test",
                )
            )
            await seed.commit()

        _as(app, admin_id, Role.ADMIN, "admin@uni.test")

        resp = test_client.patch(
            f"/api/v1/materials/{material_id}/questions/{question_id}",
            json={"status": "rejected"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
    finally:
        await _cleanup(session_factory, question_id)
        async with session_factory() as cleanup:
            await cleanup.execute(
                text('delete from "user" where user_id = :uid'), {"uid": admin_id}
            )
            await cleanup.commit()
        app.dependency_overrides.pop(get_principal, None)


async def test_nonexistent_question_returns_404_not_403(db_client, app):
    """A random id must not distinguish "not yours" from "does not exist"."""
    test_client, session_factory = db_client
    lecturer_id = uuid4()
    _as(app, lecturer_id, Role.LECTURER, "lecturer@uni.test")

    fake_material_id = uuid4()
    fake_question_id = uuid4()
    resp = test_client.patch(
        f"/api/v1/materials/{fake_material_id}/questions/{fake_question_id}",
        json={"status": "approved"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
    app.dependency_overrides.pop(get_principal, None)


async def test_review_route_rejects_unauthenticated(db_client, app):
    test_client, session_factory = db_client
    app.dependency_overrides.pop(get_principal, None)

    resp = test_client.patch(
        f"/api/v1/materials/{uuid4()}/questions/{uuid4()}",
        json={"status": "approved"},
    )

    assert resp.status_code == 401


async def test_bulk_review_approves_only_owned_questions(db_client, app):
    test_client, session_factory = db_client
    owner_id = uuid4()
    other_id = uuid4()

    mat_a, q_owned = await _seed_question(session_factory, instructor_id=owner_id)
    mat_b, q_not_owned = await _seed_question(session_factory, instructor_id=other_id)

    try:
        _as(app, owner_id, Role.LECTURER, "owner@uni.test")

        resp = test_client.post(
            f"/api/v1/materials/{mat_a}/questions:bulk",
            json={"question_ids": [str(q_owned), str(q_not_owned)], "status": "approved"},
        )

        assert resp.status_code == 200
        body = resp.json()
        # Only the owned question comes back approved; the other lecturer's
        # question is silently skipped, not a 403 for the whole batch.
        returned_ids = {item["id"] for item in body}
        assert str(q_owned) in returned_ids
        assert str(q_not_owned) not in returned_ids
    finally:
        await _cleanup(session_factory, q_owned)
        await _cleanup(session_factory, q_not_owned)
        app.dependency_overrides.pop(get_principal, None)


async def test_bulk_review_with_no_owned_ids_returns_empty_list(db_client, app):
    test_client, session_factory = db_client
    owner_id = uuid4()
    caller_id = uuid4()

    mat, q = await _seed_question(session_factory, instructor_id=owner_id)

    try:
        _as(app, caller_id, Role.LECTURER, "caller@uni.test")

        resp = test_client.post(
            f"/api/v1/materials/{mat}/questions:bulk",
            json={"question_ids": [str(q)], "status": "approved"},
        )

        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        await _cleanup(session_factory, q)
        app.dependency_overrides.pop(get_principal, None)
