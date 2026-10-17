"""A student's own-data routes: export, and asking for erasure.

Against a real database. A student reaches only their own data; a lecturer is
turned away. Rows the tests write are removed afterwards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from app.auth.store import LECTURER_ID
from app.models.audit_log import AuditLog
from app.models.deletion_request import DeletionRequest
from app.models.engagement_record import EngagementRecord
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role

from .session_support import add_course, sign_in_as

BASE = "/api/v1/me"


async def add_student(factory, created, course) -> tuple[UUID, UUID]:
    user_id = uuid4()
    async with factory() as seed:
        seed.add(
            User(user_id=user_id, name="Own Data", role="student", email=f"{user_id.hex}@t.test")
        )
        await seed.flush()
        student = Student(
            user_id=user_id,
            course_id=course.id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
        seed.add(student)
        await seed.commit()
        student_id = student.student_id
    created["user"].append(user_id)
    return user_id, student_id


@pytest.fixture
async def mine(db, app):
    client, factory, created = db
    async with factory() as probe:
        started = await probe.scalar(select(func.clock_timestamp()))
    course = await add_course(factory, created)
    user_id, student_id = await add_student(factory, created, course)
    _, other_id = await add_student(factory, created, course)
    ended = datetime.now(UTC) - timedelta(days=2)
    async with factory() as seed:
        session = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=course.id,
            start_time=ended - timedelta(hours=1),
            end_time=ended,
            ended_at=ended,
            mode="live",
            status="ended",
        )
        seed.add(session)
        await seed.flush()
        for owner in (student_id, other_id):
            seed.add(
                EngagementRecord(
                    session_id=session.session_id,
                    student_id=owner,
                    attempt_rate=1.0,
                    attention_signal="present",
                    engagement_score=0.8,
                )
            )
        await seed.commit()
    sign_in_as(app, user_id, Role.STUDENT)
    world = SimpleNamespace(
        app=app, client=client, user=user_id, student=student_id, session=session.session_id
    )
    yield world

    async with factory() as cleanup:
        await cleanup.execute(
            delete(DeletionRequest).where(DeletionRequest.requested_by == user_id)
        )
        await cleanup.execute(
            delete(AuditLog).where(AuditLog.user_id == user_id, AuditLog.timestamp >= started)
        )
        await cleanup.execute(delete(Student).where(Student.student_id.in_([student_id, other_id])))
        await cleanup.execute(
            delete(SessionModel).where(SessionModel.session_id == session.session_id)
        )
        await cleanup.commit()


def test_a_student_exports_only_their_own_data(mine):
    response = mine.client.get(f"{BASE}/data")

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["student_id"] == str(mine.student)
    assert body["account"]["user_id"] == str(mine.user)
    assert len(body["engagement"]) == 1
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]


async def test_an_export_is_audited_with_counts_only(mine, db):
    mine.client.get(f"{BASE}/data")

    _, factory, _ = db
    async with factory() as check:
        entry = (
            await check.scalars(
                select(AuditLog).where(
                    AuditLog.user_id == mine.user, AuditLog.action_type == "STUDENT_DATA_EXPORTED"
                )
            )
        ).first()
    assert entry is not None
    assert entry.details["engagement"] == 1


def test_a_lecturer_is_turned_away_from_every_route(mine):
    sign_in_as(mine.app, LECTURER_ID, Role.LECTURER)

    assert mine.client.get(f"{BASE}/data").status_code == 403
    assert mine.client.post(f"{BASE}/deletion-request", json={"confirm": True}).status_code == 403
    assert mine.client.get(f"{BASE}/deletion-request").status_code == 403


def test_a_request_must_be_confirmed(mine):
    response = mine.client.post(f"{BASE}/deletion-request", json={"confirm": False})

    assert response.status_code in (400, 422)


def test_a_student_asks_for_erasure_once_and_can_see_where_it_stands(mine):
    assert mine.client.get(f"{BASE}/deletion-request").status_code == 404

    first = mine.client.post(
        f"{BASE}/deletion-request", json={"confirm": True, "reason": "Leaving the course"}
    )
    again = mine.client.post(f"{BASE}/deletion-request", json={"confirm": True})
    status = mine.client.get(f"{BASE}/deletion-request")

    assert first.status_code == 201
    assert first.json()["status"] == "requested"
    assert "requested_by" not in first.json()
    assert again.status_code == 409
    assert status.json()["request_id"] == first.json()["request_id"]


def test_a_user_without_a_student_profile_gets_not_found(mine):
    sign_in_as(mine.app, uuid4(), Role.STUDENT)

    assert mine.client.get(f"{BASE}/data").status_code == 404
