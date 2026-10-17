"""The retention purge, against a real database.

Every test runs in a transaction that is rolled back at the end, so what the
purge deletes (including any old data already in a development database) is
never saved.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update
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

    assert runner.task_names == [
        "session-data",
        "teams-roster-syncs",
        "teams-unresolved-mappings",
    ]


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
            "teams-unresolved-mappings",
        ]
    finally:
        get_purge_runner.cache_clear()


# -- archiving into the history database -------------------------------------------------------


@pytest.fixture
async def history_tables(db):
    """The history tables, made inside this test's transaction and rolled back."""
    from app.history import models  # noqa: F401
    from app.history.database import HistoryBase

    await db.run_sync(lambda session: HistoryBase.metadata.create_all(session.connection()))


async def student_of(db, run) -> uuid.UUID:
    return await db.scalar(
        select(StudentResponse.student_id).where(StudentResponse.response_id == run.response)
    )


async def test_archiving_a_session_adds_its_totals_to_the_semester_row(db, history, history_tables):
    from app.history.repository import list_for_student, semester_label
    from app.services.history_archive import archive_sessions

    await archive_sessions(db, db, [history.expired.session])

    [row] = await list_for_student(db, await student_of(db, history.expired))
    assert row.semester == semester_label(days_ago(91))
    assert (row.sessions_attended, row.questions_attempted, row.questions_correct) == (1, 1, 1)
    assert (row.engagement_sum, row.engagement_count) == (pytest.approx(0.8), 1)
    assert row.gaze_count == 0


async def test_a_session_is_never_added_twice(db, history, history_tables):
    from app.history.repository import list_for_student
    from app.services.history_archive import archive_sessions

    await archive_sessions(db, db, [history.expired.session])
    assert await archive_sessions(db, db, [history.expired.session]) == 0

    [row] = await list_for_student(db, await student_of(db, history.expired))
    assert row.sessions_attended == 1


async def test_the_purge_archives_a_session_before_deleting_it(
    db, history, history_tables, borrowed
):
    from app.services.retention_tasks import SessionDataPurge

    await SessionDataPurge(borrowed, history=borrowed).purge(days_ago(90), 500)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)
    entry = (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.action_type == RETENTION_ACTION)
            .order_by(AuditLog.timestamp.desc())
        )
    ).first()
    assert entry.details["archived_summaries"] >= 1


async def test_nothing_is_deleted_when_the_archive_fails(
    db, history, history_tables, borrowed, monkeypatch
):
    from app.services import retention_tasks

    async def broken(*args, **kwargs):
        raise RuntimeError("the history database is down")

    monkeypatch.setattr(retention_tasks, "archive_sessions", broken)

    with pytest.raises(RuntimeError):
        await retention_tasks.SessionDataPurge(borrowed, history=borrowed).purge(days_ago(90), 500)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)


async def test_only_unresolved_old_teams_mappings_are_purged(db, borrowed):
    from app.models.teams_user_mapping import TeamsUserMapping
    from app.services.retention_tasks import TeamsMappingPurge

    owner = User(name="Mapped Student", role="student", email=f"m-{uuid.uuid4()}@example.com")
    db.add(owner)
    await db.flush()

    def mapping(user_id, age_days):
        return TeamsUserMapping(
            tenant_id=f"t-{uuid.uuid4().hex}",
            teams_user_id=f"u-{uuid.uuid4().hex}",
            user_id=user_id,
            updated_at=days_ago(age_days),
        )

    rows = {
        "old_unresolved": mapping(None, 200),
        "new_unresolved": mapping(None, 10),
        "old_resolved": mapping(owner.user_id, 200),
    }
    db.add_all(rows.values())
    await db.flush()
    ids = {name: row.mapping_id for name, row in rows.items()}

    await TeamsMappingPurge(borrowed).purge(days_ago(120), 500)

    remaining = {
        name: await db.get(TeamsUserMapping, mapping_id) is not None
        for name, mapping_id in ids.items()
    }
    assert remaining == {"old_unresolved": False, "new_unresolved": True, "old_resolved": True}


# -- a session that is not over is never purged ------------------------------------------------


@pytest.mark.parametrize("status", ["prepared", "active", "ending"])
async def test_a_session_that_is_not_over_is_never_purged(db, history, status):
    await db.execute(
        update(Session).where(Session.session_id == history.expired.session).values(status=status)
    )

    report = await purge_expired(db, dry_run=False, retention_days=90)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)
    assert report.sessions >= 0


async def test_a_cancelled_session_is_purged_like_an_ended_one(db, history):
    await db.execute(
        update(Session)
        .where(Session.session_id == history.expired.session)
        .values(status="cancelled")
    )

    await purge_expired(db, dry_run=False, retention_days=90)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)


async def test_the_scheduled_purge_also_leaves_a_live_session_alone(db, history, borrowed):
    from app.services.retention_tasks import SessionDataPurge

    await db.execute(
        update(Session).where(Session.session_id == history.expired.session).values(status="active")
    )

    await SessionDataPurge(borrowed).purge(days_ago(90), 500)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)


# -- the admin purge archives first, like the scheduled one -------------------------------------


async def test_the_admin_purge_archives_to_history_before_deleting(
    db, history, history_tables, borrowed
):
    from app.history.models import ArchivedSession
    from app.history.repository import list_for_student

    student = await student_of(db, history.expired)  # the answer is gone after the purge

    await purge_expired(db, dry_run=False, retention_days=90, history=borrowed)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)
    # One row for the student, built from the expired session only: the kept
    # session was not archived and is still there.
    [row] = await list_for_student(db, student)
    assert (row.sessions_attended, row.questions_attempted) == (1, 1)
    archived = await db.scalar(
        select(func.count())
        .select_from(ArchivedSession)
        .where(ArchivedSession.session_id == history.expired.session)
    )
    assert archived == 1
    assert await holdings(db, history.kept) == dict.fromkeys(HOLDINGS, 1)


async def test_the_admin_purge_deletes_nothing_when_history_is_unavailable(
    db, history, history_tables
):
    def broken():
        raise RuntimeError("the history database is down")

    with pytest.raises(RuntimeError):
        await purge_expired(db, dry_run=False, retention_days=90, history=lambda: broken)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)


# -- attendance comes from the attendance table ---------------------------------------------------


async def test_a_student_who_only_attended_still_gets_a_history_row(db, history, history_tables):
    from datetime import date

    from app.history.repository import list_for_student
    from app.models.session_participant import SessionParticipant
    from app.services.history_archive import archive_sessions

    course = await db.scalar(
        select(Session.course_id).where(Session.session_id == history.expired.session)
    )
    quiet_user = User(name="Quiet Student", role="student", email=f"q-{uuid.uuid4()}@example.com")
    db.add(quiet_user)
    await db.flush()
    quiet = Student(
        user_id=quiet_user.user_id,
        course_id=course,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    db.add(quiet)
    await db.flush()
    db.add(SessionParticipant(session_id=history.expired.session, student_id=quiet.student_id))
    await db.flush()

    await archive_sessions(db, db, [history.expired.session])

    [row] = await list_for_student(db, quiet.student_id)
    assert (row.sessions_attended, row.questions_attempted, row.questions_correct) == (1, 0, 0)
    assert (row.engagement_count, row.gaze_count) == (0, 0)
    [answered] = await list_for_student(db, await student_of(db, history.expired))
    assert answered.questions_attempted == 1


# -- a failure between the two databases ------------------------------------------------------


@pytest.fixture
async def separate_history():
    """A real second database for history, so its commits are independent of the
    main one. Skips when the PostgreSQL tools or the right to create one are missing."""
    import asyncio
    import shutil
    import subprocess

    from sqlalchemy.engine import make_url

    from app.history.database import create_history_tables
    from scripts.database_backup import connection_args, drop, environment, plain_url

    if any(shutil.which(tool) is None for tool in ("createdb", "dropdb")):
        pytest.skip("the PostgreSQL client tools are not installed")
    live = get_settings().database_url
    url = plain_url(live)
    name = f"clip_history_test_{uuid.uuid4().hex[:8]}"
    created = await asyncio.to_thread(
        subprocess.run,
        ["createdb", *connection_args(url), name],
        env=environment(url),
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip(f"this database user may not create databases: {created.stderr.strip()}")
    engine = create_async_engine(make_url(live).set(database=name), poolclass=NullPool)
    await create_history_tables(engine)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()
    drop(live, name)


@pytest.fixture
def main_that_rolls_back(db, monkeypatch):
    """The main database for a task that opens and commits its own session: a
    commit is a flush, and an error undoes what the task did, as a real rollback."""
    from contextlib import asynccontextmanager

    async def flush_only():
        await db.flush()

    monkeypatch.setattr(db, "commit", flush_only)

    @asynccontextmanager
    async def session():
        nested = await db.begin_nested()
        try:
            yield db
        except BaseException:
            await nested.rollback()
            raise
        else:
            await nested.commit()

    return lambda: session


async def test_a_scheduled_purge_that_stops_between_the_two_commits_is_finished_by_the_next_run(
    db, history, main_that_rolls_back, separate_history, monkeypatch
):
    from app.history.models import ArchivedSession
    from app.history.repository import list_for_student
    from app.services import retention_tasks

    student = await student_of(db, history.expired)
    real = retention_tasks.record_event
    attempts = []

    async def fails_once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the main database failed after the archive was committed")
        return await real(*args, **kwargs)

    monkeypatch.setattr(retention_tasks, "record_event", fails_once)
    task = retention_tasks.SessionDataPurge(main_that_rolls_back, history=lambda: separate_history)

    with pytest.raises(RuntimeError):
        await task.purge(days_ago(90), 500)

    # Between the two commits: archived in history, still in the main database.
    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)
    async with separate_history() as check:
        [row] = await list_for_student(check, student)
        assert row.sessions_attended == 1

    await task.purge(days_ago(90), 500)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)
    async with separate_history() as check:
        [row] = await list_for_student(check, student)
        assert row.sessions_attended == 1  # not counted a second time
        archived = await check.scalar(
            select(func.count())
            .select_from(ArchivedSession)
            .where(ArchivedSession.session_id == history.expired.session)
        )
        assert archived == 1


async def test_an_admin_purge_that_stops_between_the_two_commits_is_finished_by_the_next_run(
    db, history, separate_history, monkeypatch
):
    from app.history.repository import list_for_student
    from app.services import retention as retention_module

    student = await student_of(db, history.expired)
    real = retention_module.record_event
    attempts = []

    async def fails_once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the main database failed after the archive was committed")
        return await real(*args, **kwargs)

    monkeypatch.setattr(retention_module, "record_event", fails_once)

    nested = await db.begin_nested()
    with pytest.raises(RuntimeError):
        await purge_expired(db, dry_run=False, retention_days=90, history=lambda: separate_history)
    await nested.rollback()

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 1)

    await purge_expired(db, dry_run=False, retention_days=90, history=lambda: separate_history)

    assert await holdings(db, history.expired) == dict.fromkeys(HOLDINGS, 0)
    async with separate_history() as check:
        [row] = await list_for_student(check, student)
        assert row.sessions_attended == 1
