"""Engagement across a term, against a real database. Rolled back after each test."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.consideration_request import ConsiderationRequest
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.services.engagement_history import engagement_history, is_quiet

from .database_support import require_database


def test_quiet_means_missing_most_classes_or_answering_little() -> None:
    assert is_quiet(4, 3, 1, 1)
    assert not is_quiet(4, 2, 2, 2)
    assert is_quiet(4, 0, 4, 1)
    assert not is_quiet(4, 0, 4, 2)
    assert not is_quiet(4, 0, 2, 0), "too few checkpoints to say"
    assert not is_quiet(1, 1, 0, 0), "one class is not a pattern"


@pytest.fixture
async def db():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _student(db, course, name):
    user = User(name=name, role="student", email=f"{uuid.uuid4().hex[:10]}@example.com")
    db.add(user)
    await db.flush()
    student = Student(
        user_id=user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    db.add(student)
    await db.flush()
    return student


@pytest.fixture
async def term(db):
    """Four finished classes. Ada joins and answers all; Ben misses three;
    Cy joins all and answers none; Dee is like Ben but has an approved
    consideration."""
    lecturer = User(name="Lecturer", role="lecturer", email=f"l-{uuid.uuid4().hex[:8]}@example.com")
    other = User(name="Other", role="lecturer", email=f"o-{uuid.uuid4().hex[:8]}@example.com")
    course = Course(code=f"EH{uuid.uuid4().hex[:6]}".upper(), name="History")
    db.add_all([lecturer, other, course])
    await db.flush()
    ada, ben, cy, dee = [await _student(db, course, n) for n in ("Ada", "Ben", "Cy", "Dee")]
    db.add(ConsiderationRequest(student_id=dee.student_id, needs=["prompts"], status="approved"))
    material = Material(
        course_id=course.id,
        uploaded_by_user_id=lecturer.user_id,
        filename="m.pdf",
        content_type="application/pdf",
        size_bytes=1,
        status="completed",
    )
    db.add(material)
    await db.flush()
    now = datetime.now(UTC)
    sessions = []
    for week in range(4):
        start = now - timedelta(days=7 * (4 - week))
        session = Session(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            title=f"Week {week + 1}",
            start_time=start,
            end_time=start + timedelta(hours=1),
            ended_at=start + timedelta(hours=1),
            mode="live",
            status="ended",
        )
        db.add(session)
        await db.flush()
        question = Question(
            source_material_id=material.id,
            session_id=session.session_id,
            question_text="Q?",
            question_type="mcq",
            status="delivered",
            difficulty="easy",
            options=["a", "b"],
            correct_option=0,
        )
        db.add(question)
        await db.flush()
        present = [ada, cy] + ([ben, dee] if week == 0 else [])
        db.add(
            DeliveredQuestion(
                session_id=session.session_id,
                question_id=question.question_id,
                delivered_at=start,
                closes_at=start + timedelta(minutes=1),
                window_seconds=60,
                eligible_count=len(present),
                respondent_count=1 + (1 if week == 0 else 0),
            )
        )
        for student in present:
            db.add(
                SessionParticipant(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    joined_at=start,
                    last_seen_at=start,
                )
            )
        for student in [ada] + ([ben] if week == 0 else []):
            db.add(
                StudentResponse(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    question_id=question.question_id,
                    selected_option=0,
                    is_correct=student is ada,
                )
            )
        for student in [ada, cy] if week == 3 else [ada]:
            db.add(
                AttentionSignalSummary(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    window_start=start,
                    window_seconds=60,
                    sample_count=10,
                    gaze_on_screen_ratio=0.8,
                )
            )
        sessions.append(session)
    await db.flush()
    return lecturer, other, course, sessions


async def test_each_class_is_a_row_newest_first(db, term) -> None:
    lecturer, _, course, sessions = term
    history = await engagement_history(db, instructor_id=lecturer.user_id, course_id=course.id)
    assert [row.title for row in history.sessions] == ["Week 4", "Week 3", "Week 2", "Week 1"]
    first = history.sessions[-1]
    assert first.present == 4 and first.checkpoints == 1
    assert first.answer_rate == 0.5
    assert first.correct_rate == 0.5
    assert history.sessions[0].answer_rate == 0.5


async def test_attention_is_hidden_until_three_students_contribute(db, term) -> None:
    lecturer, _, course, _ = term
    history = await engagement_history(db, instructor_id=lecturer.user_id, course_id=course.id)
    assert all(row.on_screen is None for row in history.sessions)


async def test_quiet_students_skip_the_accommodated(db, term) -> None:
    lecturer, _, course, _ = term
    history = await engagement_history(db, instructor_id=lecturer.user_id, course_id=course.id)
    quiet = {student.name: student for student in history.quiet}
    assert set(quiet) == {"Ben", "Cy"}
    assert quiet["Ben"].sessions_missed == 3
    assert quiet["Cy"].sessions_missed == 0 and quiet["Cy"].answer_rate == 0.0


async def test_a_lecturer_sees_only_their_own_classes(db, term) -> None:
    _, other, course, _ = term
    history = await engagement_history(db, instructor_id=other.user_id, course_id=course.id)
    assert history.sessions == [] and history.quiet == []
    everyone = await engagement_history(db, instructor_id=None, course_id=course.id)
    assert len(everyone.sessions) == 4
