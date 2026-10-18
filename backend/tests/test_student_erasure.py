"""Erasing a student: their own data goes, everyone else's and the proof stay.

Every test runs in a transaction that is rolled back at the end.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.ai_alert import AIAlert
from app.models.ai_recommendation import AIRecommendation
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.comprehension_result import ComprehensionResult
from app.models.consent import Consent
from app.models.course import Course
from app.models.dynamic_prompt import DynamicPrompt
from app.models.engagement_record import EngagementRecord
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.teams_participant_mapping import TeamsParticipantMapping
from app.models.teams_roster_sync import TeamsRosterSync
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User
from app.repositories.audit_repository import list_events, record_event
from app.services.student_erasure import erase_student

from .database_support import require_database

HOLDINGS = ("answers", "labels", "prompts", "engagement", "attention")


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
async def classroom(db):
    """A student who leaves and one who stays, in the same finished session, each
    with an answer, its label, a prompt, engagement and an attention summary. The
    one who leaves also has a profile, Teams records, a consent and an audit entry."""
    lecturer = User(name="Erasure Lecturer", role="lecturer", email=f"l-{uuid.uuid4()}@example.com")
    leaver_user = User(
        name="Leaving Student", role="student", email=f"a-{uuid.uuid4()}@example.com"
    )
    stayer_user = User(
        name="Staying Student", role="student", email=f"b-{uuid.uuid4()}@example.com"
    )
    course = Course(code=f"ER-{uuid.uuid4().hex[:8]}", name="Erasure")
    db.add_all([lecturer, leaver_user, stayer_user, course])
    await db.flush()
    leaver = Student(
        user_id=leaver_user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
        accessibility_need="Extra time",
        special_consideration_status="approved",
    )
    stayer = Student(
        user_id=stayer_user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    material = Material(
        course_id=course.id,
        uploaded_by_user_id=lecturer.user_id,
        filename="erasure.pdf",
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
    db.add_all([leaver, stayer, material, session])
    await db.flush()
    question = Question(
        source_material_id=material.id,
        session_id=session.session_id,
        question_text="Which option is correct?",
        question_type="mcq",
        status="delivered",
        difficulty="easy",
        topic="Erasure",
        options=["Incorrect", "Correct"],
        correct_option=1,
    )
    db.add(question)
    await db.flush()

    async def give(student: Student) -> uuid.UUID:
        response = StudentResponse(
            session_id=session.session_id,
            student_id=student.student_id,
            question_id=question.question_id,
            selected_option=1,
            is_correct=True,
        )
        db.add(response)
        await db.flush()
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
            ]
        )
        await db.flush()
        return response.response_id

    leaver_response = await give(leaver)
    stayer_response = await give(stayer)

    sync = TeamsRosterSync(
        meeting_id=f"meeting-{uuid.uuid4().hex}",
        session_id=session.session_id,
        source_event_id="event-1",
        event_type="snapshot",
    )
    db.add(sync)
    await db.flush()
    db.add_all(
        [
            TeamsUserMapping(
                tenant_id="tenant",
                teams_user_id=f"teams-{uuid.uuid4().hex}",
                user_id=leaver_user.user_id,
            ),
            TeamsParticipantMapping(
                sync_id=sync.sync_id,
                record_index=0,
                tenant_id="tenant",
                teams_user_id="teams-user",
                display_name="Leaving Student",
                user_id=leaver_user.user_id,
                match_status="matched",
            ),
            Consent(user_id=leaver_user.user_id, consent_type="terms", granted=True),
        ]
    )
    await record_event(
        db,
        action_type="TEST_BEFORE_ERASURE",
        user_id=leaver_user.user_id,
        target_type="student",
        target_id=leaver.student_id,
    )
    await db.flush()
    return SimpleNamespace(
        lecturer_user=lecturer.user_id,
        course=course.id,
        session=session.session_id,
        question=question.question_id,
        sync=sync.sync_id,
        leaver=leaver.student_id,
        leaver_user=leaver_user.user_id,
        leaver_response=leaver_response,
        stayer=stayer.student_id,
        stayer_user=stayer_user.user_id,
        stayer_response=stayer_response,
    )


async def count(db, model, column, value) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(column == value)) or 0


async def holdings(db, student_id, response_id) -> dict[str, int]:
    return {
        "answers": await count(db, StudentResponse, StudentResponse.student_id, student_id),
        "labels": await count(
            db, ComprehensionResult, ComprehensionResult.response_id, response_id
        ),
        "prompts": await count(db, DynamicPrompt, DynamicPrompt.student_id, student_id),
        "engagement": await count(db, EngagementRecord, EngagementRecord.student_id, student_id),
        "attention": await count(
            db, AttentionSignalSummary, AttentionSignalSummary.student_id, student_id
        ),
    }


async def test_a_students_own_data_is_erased(db, classroom):
    report = await erase_student(db, classroom.leaver)

    assert await holdings(db, classroom.leaver, classroom.leaver_response) == dict.fromkeys(
        HOLDINGS, 0
    )
    assert await count(db, Student, Student.student_id, classroom.leaver) == 0
    assert report.as_counts() == {
        "answers": 1,
        "attention_summaries": 1,
        "prompts": 1,
        "engagement": 1,
        "teams_records": 2,
        "alerts": 0,
        "recommendations": 0,
    }


async def test_another_students_data_is_untouched(db, classroom):
    await erase_student(db, classroom.leaver)

    assert await holdings(db, classroom.stayer, classroom.stayer_response) == dict.fromkeys(
        HOLDINGS, 1
    )
    assert await count(db, Student, Student.student_id, classroom.stayer) == 1


async def test_the_class_itself_is_untouched(db, classroom):
    await erase_student(db, classroom.leaver)

    assert await count(db, Session, Session.session_id, classroom.session) == 1
    assert await count(db, Question, Question.question_id, classroom.question) == 1


async def test_the_account_no_longer_identifies_anyone_and_cannot_sign_in(db, classroom):
    await erase_student(db, classroom.leaver)

    account = (
        await db.execute(
            select(User.name, User.email, User.active, User.password_hash).where(
                User.user_id == classroom.leaver_user
            )
        )
    ).one()
    assert account.name == "Deleted student"
    assert account.email.endswith("@deleted.invalid")
    assert account.active is False
    assert account.password_hash is None


async def test_the_audit_log_and_consent_records_survive(db, classroom):
    await erase_student(db, classroom.leaver)

    entries, _ = await list_events(db, target_type="student", target_id=classroom.leaver)
    assert [e.action_type for e in entries] == ["TEST_BEFORE_ERASURE"]
    assert await count(db, Consent, Consent.user_id, classroom.leaver_user) == 1


async def test_teams_ids_and_names_pointing_at_the_account_are_cleared(db, classroom):
    await erase_student(db, classroom.leaver)

    assert await count(db, TeamsUserMapping, TeamsUserMapping.user_id, classroom.leaver_user) == 0
    row = (
        await db.execute(
            select(
                TeamsParticipantMapping.display_name,
                TeamsParticipantMapping.teams_user_id,
                TeamsParticipantMapping.user_id,
            ).where(TeamsParticipantMapping.sync_id == classroom.sync)
        )
    ).one()
    assert (row.display_name, row.teams_user_id, row.user_id) == (None, None, None)


async def test_erasing_a_student_twice_is_safe(db, classroom):
    await erase_student(db, classroom.leaver)

    again = await erase_student(db, classroom.leaver)

    assert again.as_counts() == dict.fromkeys(
        (
            "answers",
            "attention_summaries",
            "prompts",
            "engagement",
            "teams_records",
            "alerts",
            "recommendations",
        ),
        0,
    )


async def test_only_a_student_account_is_anonymised(db, classroom):
    odd = Student(
        user_id=classroom.lecturer_user,
        course_id=classroom.course,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    db.add(odd)
    await db.flush()

    await erase_student(db, odd.student_id)

    account = (
        await db.execute(
            select(User.name, User.active).where(User.user_id == classroom.lecturer_user)
        )
    ).one()
    assert (account.name, account.active) == ("Erasure Lecturer", True)


async def test_alerts_and_recommendations_about_the_student_are_deleted(db, classroom):
    def alert(student):
        return AIAlert(
            session_id=classroom.session,
            student_id=student,
            kind="comprehension",
            message="This student is struggling with the topic.",
            reason="Several wrong answers in a row.",
            confidence=0.7,
        )

    def recommendation(student):
        return AIRecommendation(
            session_id=classroom.session,
            student_id=student,
            recommendation="Revisit the topic with this student.",
            reason="Several wrong answers in a row.",
            confidence=0.7,
        )

    db.add_all(
        [
            alert(classroom.leaver),
            alert(classroom.stayer),
            recommendation(classroom.leaver),
            recommendation(classroom.stayer),
        ]
    )
    await db.flush()

    report = await erase_student(db, classroom.leaver)

    assert (report.alerts, report.recommendations) == (1, 1)
    assert await count(db, AIAlert, AIAlert.student_id, classroom.leaver) == 0
    assert await count(db, AIRecommendation, AIRecommendation.student_id, classroom.leaver) == 0
    # Nothing was merely unlinked: the leaver's rows are gone and the stayer's remain.
    assert await count(db, AIAlert, AIAlert.session_id, classroom.session) == 1
    assert await count(db, AIRecommendation, AIRecommendation.session_id, classroom.session) == 1
