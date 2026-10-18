"""An erasure and a purge that overlap must not leave a student's history behind.

Against a real database, and a real second one for history. The data is committed,
because the two sides run on separate connections, and it is removed afterwards.
The session is ten years old, so a purge up to a day after it touches nothing else.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.course import Course
from app.models.deletion_request import DeletionRequest
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.user import User
from app.services import deletion_requests
from app.services.retention_tasks import SessionDataPurge

from .database_support import require_database
from .test_deletion_requests import separate_history  # noqa: F401  (a real second database)


@pytest.fixture
async def committed():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    started = datetime.now(UTC)
    ended = started - timedelta(days=3650)
    async with factory() as db:
        lecturer = User(name="Race Lecturer", role="lecturer", email=f"l-{uuid.uuid4()}@t.test")
        learner = User(name="Race Student", role="student", email=f"s-{uuid.uuid4()}@t.test")
        requester = User(name="Race Admin", role="admin", email=f"a-{uuid.uuid4()}@t.test")
        approver = User(name="Race Admin Two", role="admin", email=f"b-{uuid.uuid4()}@t.test")
        course = Course(code=f"RC-{uuid.uuid4().hex[:8]}", name="Race")
        db.add_all([lecturer, learner, requester, approver, course])
        await db.flush()
        student = Student(
            user_id=learner.user_id,
            course_id=course.id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
        session = Session(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            start_time=ended - timedelta(hours=1),
            end_time=ended,
            ended_at=ended,
            mode="live",
            status="ended",
        )
        db.add_all([student, session])
        await db.flush()
        db.add(SessionParticipant(session_id=session.session_id, student_id=student.student_id))
        await db.flush()
        request = await deletion_requests.create_request(
            db,
            target_type="student",
            target_id=student.student_id,
            requested_by=requester.user_id,
        )
        await deletion_requests.approve(db, request.request_id, admin_id=approver.user_id)
        await db.commit()
        world = SimpleNamespace(
            factory=factory,
            ended=ended,
            student=student.student_id,
            session=session.session_id,
            course=course.id,
            request=request.request_id,
            approver=approver.user_id,
            users=[lecturer.user_id, learner.user_id, requester.user_id, approver.user_id],
        )

    yield world

    async with factory() as cleanup:
        await cleanup.execute(
            delete(DeletionRequest).where(DeletionRequest.request_id == world.request)
        )
        await cleanup.execute(delete(AuditLog).where(AuditLog.user_id.in_(world.users)))
        await cleanup.execute(
            delete(AuditLog).where(
                AuditLog.user_id.is_(None),
                AuditLog.action_type == "RETENTION_PURGE",
                AuditLog.timestamp >= started,
            )
        )
        await cleanup.execute(delete(Session).where(Session.session_id == world.session))
        await cleanup.execute(delete(Student).where(Student.student_id == world.student))
        await cleanup.execute(delete(Course).where(Course.id == world.course))
        await cleanup.execute(delete(User).where(User.user_id.in_(world.users)))
        await cleanup.commit()
    await engine.dispose()


async def test_an_erasure_and_a_purge_that_overlap_leave_no_history_behind(
    committed,
    separate_history,  # noqa: F811
    monkeypatch,
):
    from app.history.repository import list_for_student

    in_the_gap = asyncio.Event()
    carry_on = asyncio.Event()
    real = deletion_requests._erase_history

    async def pause_after_the_history_commit(student_id, history):
        removed = await real(student_id, history)
        in_the_gap.set()  # the history is erased and committed; the main commit is not
        await carry_on.wait()
        return removed

    monkeypatch.setattr(deletion_requests, "_erase_history", pause_after_the_history_commit)

    async def erase():
        async with committed.factory() as db:
            await deletion_requests.execute(
                db,
                committed.request,
                admin_id=committed.approver,
                history=lambda: separate_history,
            )
            await db.commit()

    erasure = asyncio.create_task(erase())
    purge = None
    try:
        await asyncio.wait_for(in_the_gap.wait(), timeout=15)
        # The dangerous moment: the student is still in the main database. The purge
        # must not read and archive them now, so it has to wait for the erasure.
        purge = asyncio.create_task(
            SessionDataPurge(lambda: committed.factory, history=lambda: separate_history).purge(
                committed.ended + timedelta(days=1), 500
            )
        )
        await asyncio.sleep(1)
        assert not purge.done(), "the purge did not wait for the erasure in progress"
    finally:
        # Always let the erasure finish, or the locks it holds would block the clean-up.
        carry_on.set()
        await asyncio.wait_for(erasure, timeout=15)
        if purge is not None:
            await asyncio.wait_for(purge, timeout=15)

    async with separate_history() as check:
        assert await list_for_student(check, committed.student) == []
