"""The retention purge, against a real database.

Every test runs in a transaction that is rolled back at the end, so what the
purge deletes (including any old data already in a development database) is
never saved.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.audit_log import AuditLog
from app.models.comprehension_result import ComprehensionResult
from app.models.course import Course
from app.models.dynamic_prompt import DynamicPrompt
from app.models.engagement_record import EngagementRecord
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.teams_roster_sync import TeamsRosterSync
from app.models.user import User
from app.services.retention import RETENTION_ACTION, purge_expired

from .database_support import require_database

HOLDINGS = ("session", "answers", "labels", "prompts", "engagement", "attention")


def days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


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
async def history(db):
    """One student with a session that ended 91 days ago and one that ended 89,
    each holding an answer, its label, a prompt, engagement, an attention
    summary, a question and a Teams roster sync."""
    lecturer = User(
        name="Retention Lecturer", role="lecturer", email=f"l-{uuid.uuid4()}@example.com"
    )
    learner = User(name="Retention Student", role="student", email=f"s-{uuid.uuid4()}@example.com")
    course = Course(code=f"RT-{uuid.uuid4().hex[:8]}", name="Retention")
    db.add_all([lecturer, learner, course])
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
        filename="retention.pdf",
        content_type="application/pdf",
        size_bytes=10,
        status="completed",
    )
    db.add_all([student, material])
    await db.flush()

    async def make_session(age_days: int):
        ended = days_ago(age_days)
        session = Session(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            start_time=ended - timedelta(hours=1),
            end_time=ended,
            ended_at=ended,
            mode="live",
            status="ended",
        )
        db.add(session)
        await db.flush()
        question = Question(
            source_material_id=material.id,
            session_id=session.session_id,
            question_text="Which option is correct?",
            question_type="mcq",
            status="delivered",
            difficulty="easy",
            topic="Retention",
            options=["Incorrect", "Correct"],
            correct_option=1,
        )
        db.add(question)
        await db.flush()
        response = StudentResponse(
            session_id=session.session_id,
            student_id=student.student_id,
            question_id=question.question_id,
            selected_option=1,
            is_correct=True,
        )
        db.add(response)
        await db.flush()
        meeting = f"meeting-{uuid.uuid4().hex}"
        db.add_all(
            [
                ComprehensionResult(
                    response_id=response.response_id,
                    label="mastered",
                    confidence_score=0.9,
                    score=1.0,
                    ai_feedback_text="Well done.",
                ),
                DynamicPrompt(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    response_status="acknowledged",
                ),
                EngagementRecord(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    attempt_rate=1.0,
                    attention_signal="present",
                    engagement_score=0.8,
                ),
                AttentionSignalSummary(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    window_start=ended,
                    window_seconds=60.0,
                    sample_count=12,
                ),
                TeamsRosterSync(
                    meeting_id=meeting,
                    session_id=session.session_id,
                    source_event_id="event-1",
                    event_type="snapshot",
                    received_at=ended,
                ),
            ]
        )
        await db.flush()
        return SimpleNamespace(
            session=session.session_id,
            question=question.question_id,
            response=response.response_id,
            meeting=meeting,
        )

    return SimpleNamespace(
        actor=lecturer.user_id,
        expired=await make_session(91),
        kept=await make_session(89),
    )


async def holdings(db, run) -> dict[str, int]:
    """How many rows of each kind a session still has."""
    rows = (
        ("session", Session, Session.session_id, run.session),
        ("answers", StudentResponse, StudentResponse.session_id, run.session),
        ("labels", ComprehensionResult, ComprehensionResult.response_id, run.response),
        ("prompts", DynamicPrompt, DynamicPrompt.session_id, run.session),
        ("engagement", EngagementRecord, EngagementRecord.session_id, run.session),
        ("attention", AttentionSignalSummary, AttentionSignalSummary.session_id, run.session),
    )
    counts = {}
    for name, model, column, value in rows:
        counts[name] = (
            await db.scalar(select(func.count()).select_from(model).where(column == value)) or 0
        )
    return counts


async def roster_syncs(db, run) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(TeamsRosterSync)
            .where(TeamsRosterSync.meeting_id == run.meeting)
        )
        or 0
    )


async def test_a_dry_run_reports_but_deletes_nothing(db, history):
    report = await purge_expired(db, dry_run=True, retention_days=90)

    assert report.dry_run is True
    assert report.sessions >= 1
    assert report.answers >= 1
    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)
    assert await roster_syncs(db, history.expired) == 1


async def test_a_dry_run_is_the_default(db, history):
    report = await purge_expired(db, retention_days=90)

    assert report.dry_run is True
    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)


async def test_a_session_past_the_cutoff_is_purged_with_everything_it_holds(db, history):
    report = await purge_expired(db, dry_run=False, retention_days=90)

    assert report.sessions >= 1
    assert report.answers >= 1
    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)


async def test_a_session_inside_the_period_is_kept_whole(db, history):
    await purge_expired(db, dry_run=False, retention_days=90)

    assert await holdings(db, history.kept) == dict.fromkeys(HOLDINGS, 1)
    assert await roster_syncs(db, history.kept) == 1


async def test_old_roster_syncs_are_purged_on_their_own_date(db, history):
    await purge_expired(db, dry_run=False, retention_days=90)

    assert await roster_syncs(db, history.expired) == 0


async def test_questions_outlive_the_session_they_were_used_in(db, history):
    await purge_expired(db, dry_run=False, retention_days=90)

    row = (
        await db.execute(
            select(Question.question_id, Question.session_id).where(
                Question.question_id == history.expired.question
            )
        )
    ).one()
    assert row.session_id is None


async def test_a_purge_is_audited_and_never_touches_the_audit_log(db, history):
    old_entry = AuditLog(
        user_id=history.actor,
        action_type="TEST_OLD_ENTRY",
        ip_address="203.0.113.1",
        timestamp=days_ago(400),
    )
    db.add(old_entry)
    await db.flush()

    await purge_expired(db, dry_run=False, retention_days=90, actor_id=history.actor)

    survivors = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.log_id == old_entry.log_id)
    )
    assert survivors == 1
    [entry] = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action_type == RETENTION_ACTION, AuditLog.user_id == history.actor
            )
        )
    ).scalars()
    assert entry.details["retention_days"] == 90
    assert entry.details["sessions"] >= 1


async def test_a_dry_run_writes_no_audit_entry(db, history):
    await purge_expired(db, dry_run=True, retention_days=90, actor_id=history.actor)

    written = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action_type == RETENTION_ACTION, AuditLog.user_id == history.actor)
    )
    assert written == 0


async def test_the_retention_period_must_be_positive():
    with pytest.raises(ValueError):
        await purge_expired(None, retention_days=0)


# -- the scheduled purge tasks ---------------------------------------------------------------


@pytest.fixture
def borrowed(db, monkeypatch):
    """The tasks open their own session and commit. Lend them this test's
    transaction instead, and make a commit only a flush, so it is rolled back."""
    from contextlib import asynccontextmanager

    async def flush_only():
        await db.flush()

    monkeypatch.setattr(db, "commit", flush_only)

    @asynccontextmanager
    async def session():
        yield db

    return lambda: session


async def test_the_session_task_purges_what_is_past_the_cutoff(db, history, borrowed):
    from app.services.retention_tasks import SessionDataPurge

    removed = await SessionDataPurge(borrowed).purge(days_ago(90), 500)

    assert removed >= 1
    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)
    assert await holdings(db, history.kept) == dict.fromkeys(HOLDINGS, 1)


async def test_the_session_task_audits_counts_as_the_system(db, history, borrowed):
    from app.services.retention_tasks import SessionDataPurge

    await SessionDataPurge(borrowed).purge(days_ago(90), 500)

    entry = (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.action_type == RETENTION_ACTION)
            .order_by(AuditLog.timestamp.desc())
        )
    ).first()
    assert entry is not None
    assert entry.user_id is None
    assert entry.details["task"] == "session-data"
    assert entry.details["sessions"] >= 1


async def test_the_roster_task_purges_old_syncs_only(db, history, borrowed):
    from app.services.retention_tasks import RosterSyncPurge

    removed = await RosterSyncPurge(borrowed).purge(days_ago(90), 500)

    assert removed >= 1
    assert await roster_syncs(db, history.expired) == 0
    assert await roster_syncs(db, history.kept) == 1


async def test_a_task_with_nothing_due_deletes_nothing_and_audits_nothing(db, borrowed):
    from app.services.retention_tasks import SessionDataPurge

    removed = await SessionDataPurge(borrowed).purge(datetime(1990, 1, 1, tzinfo=UTC), 500)

    assert removed == 0


def test_the_tasks_are_registered_once():
    from app.services.purge_runner import PurgeRunner
    from app.services.retention_tasks import register_database_purges

    runner = PurgeRunner(retention=lambda: timedelta(days=90))
    register_database_purges(runner)
    register_database_purges(runner)

    assert runner.task_names == ["session-data", "teams-roster-syncs"]


def test_housekeeping_registers_the_database_purges():
    from app.main import housekeeping
    from app.services.purge_runner import get_purge_runner

    get_purge_runner.cache_clear()
    try:
        housekeeping()
        assert get_purge_runner().task_names == [
            "session-data",
            "stored-uploads",
            "teams-roster-syncs",
        ]
    finally:
        get_purge_runner.cache_clear()
