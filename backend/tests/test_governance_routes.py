"""Governance routes: deletion requests, the audit log and the retention purge.

Against a real database, as the routes are used. Admin only: a lecturer or an
unauthenticated caller is turned away from every route. The retention run route
commits for real, so its test replaces the purge with a fake and checks only the
wiring; the purge itself is tested, rolled back, in test_retention.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update

from app.auth.store import ADMIN_ID, LECTURER_ID
from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.deletion_request import DeletionRequest
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role
from app.services import retention
from app.services.retention import PurgeReport

from .session_support import add_course, sign_in_as

BASE = "/api/v1/governance"


async def add_admin(factory, created) -> UUID:
    user_id = uuid4()
    async with factory() as seed:
        seed.add(
            User(user_id=user_id, name="Second Admin", role="admin", email=f"{user_id.hex}@t.test")
        )
        await seed.commit()
    created["user"].append(user_id)
    return user_id


@pytest.fixture
async def governance(db, app):
    """Two admins, a course and a finished session with nothing in it. What the
    tests write to the audit log and the request table is removed afterwards."""
    client, factory, created = db
    async with factory() as probe:
        started = await probe.scalar(select(func.clock_timestamp()))
    second = await add_admin(factory, created)
    course = await add_course(factory, created)
    ended = datetime.now(UTC) - timedelta(days=5)
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
        await seed.commit()

    world = SimpleNamespace(
        app=app,
        client=client,
        factory=factory,
        first=ADMIN_ID,
        second=second,
        course=course,
        session=session.session_id,
        created=created,
    )
    yield world

    admins = [world.first, world.second]
    async with factory() as cleanup:
        await cleanup.execute(
            delete(DeletionRequest).where(
                DeletionRequest.requested_by.in_(admins), DeletionRequest.requested_at >= started
            )
        )
        await cleanup.execute(
            delete(AuditLog).where(AuditLog.user_id.in_(admins), AuditLog.timestamp >= started)
        )
        await cleanup.commit()


def act_as(world, user_id: UUID) -> None:
    sign_in_as(world.app, user_id, Role.ADMIN)


def file_request(world, **overrides):
    act_as(world, world.first)
    body = {
        "target_type": "session",
        "target_id": str(world.session),
        "reason": "Recorded by mistake",
    }
    body.update(overrides)
    return world.client.post(f"{BASE}/deletion-requests", json=body)


def decide(world, request_id: str, action: str, by: UUID | None = None):
    act_as(world, by or world.second)
    return world.client.post(f"{BASE}/deletion-requests/{request_id}/{action}")


async def add_student(world) -> tuple[UUID, UUID]:
    """A student of their own, so erasing one never touches the development account."""
    user_id = uuid4()
    async with world.factory() as seed:
        seed.add(
            User(
                user_id=user_id,
                name="Leaving Student",
                role="student",
                email=f"{user_id.hex}@t.test",
            )
        )
        await seed.flush()
        student = Student(
            user_id=user_id,
            course_id=world.course.id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
        seed.add(student)
        await seed.commit()
    world.created["user"].append(user_id)
    return user_id, student.student_id


async def session_exists(world) -> bool:
    async with world.factory() as db:
        found = await db.scalar(
            select(func.count())
            .select_from(SessionModel)
            .where(SessionModel.session_id == world.session)
        )
    return bool(found)


# -- who may use these routes -----------------------------------------------------

ROUTES = [
    ("get", "/deletion-requests", None),
    ("post", "/deletion-requests", {"target_type": "session", "target_id": str(uuid4())}),
    ("get", "/audit-log", None),
    ("get", "/retention/preview", None),
    ("post", "/retention/run", {"confirm": True}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_a_lecturer_is_turned_away(as_lecturer, method, path, body):
    response = getattr(as_lecturer, method)(f"{BASE}{path}", **({"json": body} if body else {}))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_an_unauthenticated_caller_is_turned_away(client, method, path, body):
    response = getattr(client, method)(f"{BASE}{path}", **({"json": body} if body else {}))

    assert response.status_code == 401


# -- deletion requests ------------------------------------------------------------


async def test_the_whole_flow_deletes_the_session_and_keeps_the_trail(governance):
    world = governance

    created = file_request(world)
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]
    assert created.json()["status"] == "requested"
    assert created.json()["requested_by"] == str(world.first)

    approved = decide(world, request_id, "approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by"] == str(world.second)

    done = decide(world, request_id, "execute")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "executed"
    assert done.json()["outcome"] == {"sessions": 1, "answers": 0, "roster_syncs": 0}
    assert not await session_exists(world)

    trail = world.client.get(f"{BASE}/audit-log", params={"target_id": str(world.session)})
    assert trail.status_code == 200
    assert trail.json()["total"] == 3
    assert [entry["action_type"] for entry in trail.json()["items"]] == [
        "DELETION_EXECUTED",
        "DELETION_APPROVED",
        "DELETION_REQUESTED",
    ]


async def test_the_admin_who_asked_cannot_approve(governance):
    world = governance
    request_id = file_request(world).json()["request_id"]

    response = decide(world, request_id, "approve", by=world.first)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_nothing_is_deleted_before_approval(governance):
    world = governance
    request_id = file_request(world).json()["request_id"]

    response = decide(world, request_id, "execute")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert await session_exists(world)


async def test_a_request_is_decided_once(governance):
    world = governance
    request_id = file_request(world).json()["request_id"]
    assert decide(world, request_id, "approve").status_code == 200

    assert decide(world, request_id, "approve").status_code == 409
    assert decide(world, request_id, "reject").status_code == 409


async def test_a_session_cannot_have_two_open_requests(governance):
    world = governance
    assert file_request(world).status_code == 201

    again = file_request(world)

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "CONFLICT"


async def test_a_rejected_request_leaves_room_for_a_new_one(governance):
    world = governance
    request_id = file_request(world).json()["request_id"]
    assert decide(world, request_id, "reject").json()["status"] == "rejected"

    assert file_request(world).status_code == 201


async def test_a_request_for_something_that_does_not_exist_is_not_found(governance):
    world = governance

    response = file_request(world, target_id=str(uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_an_unknown_request_is_not_found(governance):
    world = governance
    act_as(world, world.first)

    assert world.client.get(f"{BASE}/deletion-requests/{uuid4()}").status_code == 404
    assert decide(world, str(uuid4()), "approve").status_code == 404


async def test_only_sessions_and_students_can_be_requested(governance):
    world = governance

    response = file_request(world, target_type="course")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_requests_are_listed_by_status(governance):
    world = governance
    request_id = file_request(world).json()["request_id"]

    waiting = world.client.get(f"{BASE}/deletion-requests", params={"status": "requested"})
    approved = world.client.get(f"{BASE}/deletion-requests", params={"status": "approved"})

    assert set(waiting.json()) == {"items", "total", "limit", "offset"}
    assert request_id in [row["request_id"] for row in waiting.json()["items"]]
    assert request_id not in [row["request_id"] for row in approved.json()["items"]]


async def test_an_unknown_status_filter_is_refused(governance):
    world = governance
    act_as(world, world.first)

    response = world.client.get(f"{BASE}/deletion-requests", params={"status": "pending"})

    assert response.status_code == 422


async def test_a_student_request_erases_the_student_and_keeps_the_trail(governance):
    world = governance
    student_user, student_id = await add_student(world)
    created = file_request(world, target_type="student", target_id=str(student_id))
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]
    assert decide(world, request_id, "approve").status_code == 200

    done = decide(world, request_id, "execute")

    assert done.status_code == 200, done.text
    assert done.json()["status"] == "executed"
    assert set(done.json()["outcome"]) == {
        "answers",
        "attention_summaries",
        "prompts",
        "engagement",
        "teams_records",
        "alerts",
        "recommendations",
    }
    async with world.factory() as db:
        remaining = await db.scalar(
            select(func.count()).select_from(Student).where(Student.student_id == student_id)
        )
        account = (
            await db.execute(select(User.name, User.active).where(User.user_id == student_user))
        ).one()
    assert remaining == 0
    assert (account.name, account.active) == ("Deleted student", False)
    trail = world.client.get(f"{BASE}/audit-log", params={"target_id": str(student_id)})
    assert trail.json()["total"] == 3


# -- audit log --------------------------------------------------------------------


async def test_the_audit_log_can_be_filtered_and_is_paged(governance):
    world = governance
    file_request(world)

    filtered = world.client.get(
        f"{BASE}/audit-log",
        params={"action_type": "DELETION_REQUESTED", "target_id": str(world.session)},
    )
    bad_page = world.client.get(f"{BASE}/audit-log", params={"limit": 0})

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    entry = filtered.json()["items"][0]
    assert entry["user_id"] == str(world.first)
    assert entry["target_type"] == "session"
    assert entry["details"]["request_id"]
    assert bad_page.status_code == 422


# -- retention --------------------------------------------------------------------


async def test_the_preview_counts_but_deletes_nothing(governance):
    world = governance
    old = datetime.now(UTC) - timedelta(days=get_settings().data_retention_days + 10)
    async with world.factory() as db:
        await db.execute(
            update(SessionModel)
            .where(SessionModel.session_id == world.session)
            .values(ended_at=old, end_time=old, start_time=old - timedelta(hours=1))
        )
        await db.commit()
    act_as(world, world.first)

    response = world.client.get(f"{BASE}/retention/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["retention_days"] == get_settings().data_retention_days
    assert body["sessions"] >= 1
    assert await session_exists(world)


class FakePurge:
    """Stands in for the real purge, which would delete whatever is old in the
    development database for good."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, db, **kwargs):
        self.calls.append(kwargs)
        return PurgeReport(
            cutoff=datetime.now(UTC),
            dry_run=kwargs["dry_run"],
            sessions=2,
            answers=5,
            roster_syncs=1,
        )


async def test_the_purge_needs_an_explicit_confirmation(governance, monkeypatch):
    world = governance
    fake = FakePurge()
    monkeypatch.setattr(retention, "purge_expired", fake)
    act_as(world, world.first)

    for body in ({"confirm": False}, {}):
        response = world.client.post(f"{BASE}/retention/run", json=body)
        assert response.status_code == 422

    assert fake.calls == []


async def test_a_confirmed_purge_is_run_as_the_admin_who_asked(governance, monkeypatch):
    world = governance
    fake = FakePurge()
    monkeypatch.setattr(retention, "purge_expired", fake)
    act_as(world, world.first)

    response = world.client.post(f"{BASE}/retention/run", json={"confirm": True})

    assert response.status_code == 200, response.text
    assert response.json()["sessions"] == 2
    assert response.json()["dry_run"] is False
    [call] = fake.calls
    assert call["dry_run"] is False
    assert call["actor_id"] == world.first
    assert call["retention_days"] == get_settings().data_retention_days


# -- history ---------------------------------------------------------------------------------


async def test_history_says_it_is_off_when_no_history_database_is_set(governance, monkeypatch):
    from app.api.v1 import governance as routes

    monkeypatch.setattr(routes, "resolve_history_factory", lambda override=None: None)
    act_as(governance, governance.first)

    response = governance.client.get(f"{BASE}/history/{uuid4()}")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "summaries": []}


async def test_an_admin_reads_a_students_history_and_the_read_is_audited(governance, monkeypatch):
    from app.api.v1 import governance as routes
    from app.history import models  # noqa: F401
    from app.history.database import HistoryBase
    from app.history.repository import SemesterTotals, add_totals, delete_student

    async with governance.factory() as setup:
        await setup.run_sync(lambda session: HistoryBase.metadata.create_all(session.connection()))
        await setup.commit()
    student, course = uuid4(), uuid4()
    async with governance.factory() as seed:
        await add_totals(
            seed,
            [
                SemesterTotals(
                    student,
                    course,
                    "2001-H1",
                    sessions_attended=2,
                    questions_attempted=4,
                    questions_correct=3,
                    engagement_sum=1.0,
                    engagement_count=2,
                )
            ],
        )
        await seed.commit()
    monkeypatch.setattr(routes, "resolve_history_factory", lambda override=None: governance.factory)
    try:
        act_as(governance, governance.first)
        response = governance.client.get(f"{BASE}/history/{student}")

        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["summaries"] == [
            {
                "semester": "2001-H1",
                "course_id": str(course),
                "sessions_attended": 2,
                "questions_attempted": 4,
                "questions_correct": 3,
                "engagement_average": 0.5,
                "gaze_average": None,
            }
        ]
        async with governance.factory() as check:
            entry = (
                await check.scalars(
                    select(AuditLog).where(
                        AuditLog.action_type == "HISTORY_VIEWED", AuditLog.target_id == student
                    )
                )
            ).first()
        assert entry is not None
        assert entry.user_id == governance.first
        assert entry.details == {"rows": 1}
    finally:
        async with governance.factory() as cleanup:
            await delete_student(cleanup, student)
            await cleanup.commit()


def test_a_lecturer_cannot_read_history(governance):
    sign_in_as(governance.app, LECTURER_ID, Role.LECTURER)

    assert governance.client.get(f"{BASE}/history/{uuid4()}").status_code == 403
