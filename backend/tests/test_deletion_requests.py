"""Deletion requests: the request, approve, reject and execute rules, against a
real database. Every test runs in a transaction that is rolled back."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.repositories.audit_repository import list_events
from app.services.deletion_requests import (
    AlreadyOpen,
    RequestNotFound,
    SelfApproval,
    TargetNotFound,
    WrongState,
    approve,
    create_request,
    execute,
    get_request,
    list_requests,
    reject,
)

from .database_support import require_database


@pytest.fixture
async def db():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    """Two admins, a student, and a finished session holding one answer."""
    first = User(name="First Admin", role="admin", email=f"a-{uuid.uuid4()}@example.com")
    second = User(name="Second Admin", role="admin", email=f"b-{uuid.uuid4()}@example.com")
    lecturer = User(name="Lecturer", role="lecturer", email=f"l-{uuid.uuid4()}@example.com")
    learner = User(name="Student", role="student", email=f"s-{uuid.uuid4()}@example.com")
    course = Course(code=f"DR-{uuid.uuid4().hex[:8]}", name="Deletion Requests")
    db.add_all([first, second, lecturer, learner, course])
    await db.flush()
    student = Student(
        user_id=learner.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    material = Material(
        course_id=course.id,
        uploaded_by_user_id=lecturer.user_id,
        filename="requests.pdf",
        content_type="application/pdf",
        size_bytes=10,
        status="completed",
    )
    ended = datetime.now(UTC) - timedelta(days=5)
    session = Session(
        instructor_id=lecturer.user_id,
        course_id=course.id,
        start_time=ended - timedelta(hours=1),
        end_time=ended,
        ended_at=ended,
        mode="live",
        status="ended",
    )
    db.add_all([student, material, session])
    await db.flush()
    question = Question(
        source_material_id=material.id,
        session_id=session.session_id,
        question_text="Which option is correct?",
        question_type="mcq",
        status="delivered",
        difficulty="easy",
        topic="Requests",
        options=["Incorrect", "Correct"],
        correct_option=1,
    )
    db.add(question)
    await db.flush()
    db.add(
        StudentResponse(
            session_id=session.session_id,
            student_id=student.student_id,
            question_id=question.question_id,
            selected_option=1,
            is_correct=True,
        )
    )
    await db.flush()
    return SimpleNamespace(
        first=first.user_id,
        second=second.user_id,
        session=session.session_id,
        student=student.student_id,
        learner=learner.user_id,
    )


async def request_session(db, world, **overrides):
    fields = {
        "target_type": "session",
        "target_id": world.session,
        "requested_by": world.first,
        "reason": "Recorded by mistake",
    }
    fields.update(overrides)
    return await create_request(db, **fields)


async def count(db, model, column, value) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(column == value)) or 0


async def test_a_request_starts_as_requested_and_is_audited(db, world):
    request = await request_session(db, world, ip_address="203.0.113.5")

    assert request.status == "requested"
    assert request.requested_by == world.first
    assert request.reason == "Recorded by mistake"
    entries, _ = await list_events(db, target_type="session", target_id=world.session)
    assert [(e.action_type, e.user_id) for e in entries] == [("DELETION_REQUESTED", world.first)]
    assert entries[0].details["request_id"] == str(request.request_id)


async def test_a_request_for_something_that_does_not_exist_is_refused(db, world):
    with pytest.raises(TargetNotFound):
        await request_session(db, world, target_id=uuid.uuid4())
    with pytest.raises(TargetNotFound):
        await request_session(db, world, target_type="student", target_id=uuid.uuid4())


async def test_only_sessions_and_students_can_be_requested(db, world):
    with pytest.raises(ValueError):
        await request_session(db, world, target_type="course")


async def test_a_target_cannot_have_two_open_requests(db, world):
    await request_session(db, world)
    with pytest.raises(AlreadyOpen):
        await request_session(db, world, requested_by=world.second)


async def test_a_rejected_request_does_not_block_a_new_one(db, world):
    first = await request_session(db, world)
    await reject(db, first.request_id, admin_id=world.second)

    again = await request_session(db, world)

    assert again.status == "requested"


async def test_a_second_admin_can_approve(db, world):
    request = await request_session(db, world)

    approved = await approve(db, request.request_id, admin_id=world.second)

    assert approved.status == "approved"
    assert approved.decided_by == world.second
    assert approved.decided_at is not None


async def test_the_admin_who_asked_cannot_approve(db, world):
    request = await request_session(db, world)

    with pytest.raises(SelfApproval):
        await approve(db, request.request_id, admin_id=world.first)

    assert (await get_request(db, request.request_id)).status == "requested"


async def test_self_approval_can_be_allowed_deliberately(db, world):
    request = await request_session(db, world)

    approved = await approve(db, request.request_id, admin_id=world.first, allow_self_approval=True)

    assert approved.status == "approved"


async def test_a_request_can_only_be_decided_once(db, world):
    request = await request_session(db, world)
    await approve(db, request.request_id, admin_id=world.second)

    with pytest.raises(WrongState):
        await approve(db, request.request_id, admin_id=world.second)
    with pytest.raises(WrongState):
        await reject(db, request.request_id, admin_id=world.second)


async def test_nothing_is_deleted_until_a_request_is_approved(db, world):
    request = await request_session(db, world)

    with pytest.raises(WrongState):
        await execute(db, request.request_id, admin_id=world.second)

    assert await count(db, Session, Session.session_id, world.session) == 1


async def test_a_rejected_request_cannot_be_executed(db, world):
    request = await request_session(db, world)
    await reject(db, request.request_id, admin_id=world.second)

    with pytest.raises(WrongState):
        await execute(db, request.request_id, admin_id=world.second)


async def test_executing_a_session_request_deletes_the_session_and_what_it_holds(db, world):
    request = await request_session(db, world)
    await approve(db, request.request_id, admin_id=world.second)

    done = await execute(db, request.request_id, admin_id=world.second)

    assert done.status == "executed"
    assert done.executed_by == world.second
    assert done.outcome == {"sessions": 1, "answers": 1}
    assert await count(db, Session, Session.session_id, world.session) == 0
    assert await count(db, StudentResponse, StudentResponse.session_id, world.session) == 0


async def test_the_audit_trail_and_the_request_outlive_the_deletion(db, world):
    request = await request_session(db, world)
    await approve(db, request.request_id, admin_id=world.second)
    await execute(db, request.request_id, admin_id=world.second)

    entries, _ = await list_events(db, target_type="session", target_id=world.session)
    assert {e.action_type for e in entries} == {
        "DELETION_REQUESTED",
        "DELETION_APPROVED",
        "DELETION_EXECUTED",
    }
    assert (await get_request(db, request.request_id)).status == "executed"


async def test_a_session_already_gone_counts_as_done(db, world):
    request = await request_session(db, world)
    await approve(db, request.request_id, admin_id=world.second)
    # Retention purges the session after approval, before anyone executes.
    await db.execute(delete(Session).where(Session.session_id == world.session))

    done = await execute(db, request.request_id, admin_id=world.second)

    assert done.status == "executed"
    assert done.outcome == {"sessions": 0, "answers": 0}


async def test_executing_a_student_request_erases_the_student(db, world):
    request = await request_session(db, world, target_type="student", target_id=world.student)
    await approve(db, request.request_id, admin_id=world.second)

    done = await execute(db, request.request_id, admin_id=world.second)

    assert done.status == "executed"
    assert done.outcome["answers"] == 1
    assert await count(db, Student, Student.student_id, world.student) == 0
    assert await count(db, StudentResponse, StudentResponse.student_id, world.student) == 0
    name = await db.scalar(select(User.name).where(User.user_id == world.learner))
    assert name == "Deleted student"


async def test_requests_can_be_listed_by_status(db, world):
    kept = await request_session(db, world)
    other = await request_session(db, world, target_type="student", target_id=world.student)
    await reject(db, other.request_id, admin_id=world.second)

    requested, _ = await list_requests(db, status="requested")
    rejected, _ = await list_requests(db, status="rejected")

    assert kept.request_id in {r.request_id for r in requested}
    assert other.request_id in {r.request_id for r in rejected}
    assert other.request_id not in {r.request_id for r in requested}


async def test_an_unknown_request_is_not_found(db):
    with pytest.raises(RequestNotFound):
        await get_request(db, uuid.uuid4())
    with pytest.raises(RequestNotFound):
        await approve(db, uuid.uuid4(), admin_id=uuid.uuid4())


# -- the history database --------------------------------------------------------------------


@pytest.fixture
async def lent_history(db, monkeypatch):
    """The history tables inside this test's transaction, and a way to lend the
    test's session to code that opens its own. A commit is only a flush."""
    from contextlib import asynccontextmanager

    from app.history import models  # noqa: F401
    from app.history.database import HistoryBase

    await db.run_sync(lambda session: HistoryBase.metadata.create_all(session.connection()))

    async def flush_only():
        await db.flush()

    monkeypatch.setattr(db, "commit", flush_only)

    @asynccontextmanager
    async def session():
        yield db

    return lambda: session


async def test_executing_a_student_request_also_erases_their_history(db, world, lent_history):
    from app.history.repository import SemesterTotals, add_totals, list_for_student

    other = uuid.uuid4()
    await add_totals(
        db,
        [
            SemesterTotals(world.student, uuid.uuid4(), "2001-H1", sessions_attended=1),
            SemesterTotals(other, uuid.uuid4(), "2001-H1", sessions_attended=1),
        ],
    )
    request = await create_request(
        db, target_type="student", target_id=world.student, requested_by=world.first
    )
    await approve(db, request.request_id, admin_id=world.second)

    done = await execute(db, request.request_id, admin_id=world.second, history=lent_history)

    assert done.outcome["history_rows"] == 1
    assert await list_for_student(db, world.student) == []
    assert len(await list_for_student(db, other)) == 1


async def test_a_history_failure_leaves_the_request_approved_and_the_student_in_place(
    db, world, lent_history
):
    def broken():
        raise RuntimeError("the history database is down")

    request = await create_request(
        db, target_type="student", target_id=world.student, requested_by=world.first
    )
    await approve(db, request.request_id, admin_id=world.second)

    with pytest.raises(RuntimeError):
        await execute(db, request.request_id, admin_id=world.second, history=lambda: broken)

    assert (await get_request(db, request.request_id)).status == "approved"
    assert await count(db, Student, Student.student_id, world.student) == 1


async def test_the_students_export_includes_their_history(db, world, lent_history):
    from app.history.repository import SemesterTotals, add_totals
    from app.services.student_data import export_student_data

    course = uuid.uuid4()
    await add_totals(
        db,
        [
            SemesterTotals(
                world.student,
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

    data = await export_student_data(db, world.learner, history=lent_history)

    assert data["history"] == [
        {
            "semester": "2001-H1",
            "course_id": str(course),
            "sessions_attended": 2,
            "questions_attempted": 4,
            "questions_correct": 3,
            "engagement_average": pytest.approx(0.5),
            "gaze_average": None,
        }
    ]
