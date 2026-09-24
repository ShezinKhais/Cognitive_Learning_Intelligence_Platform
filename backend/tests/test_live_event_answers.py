"""Database tests for LiveEventRepository.answers_to_question."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.student import Student
from app.models.user import User
from app.repositories.live_event_repository import LiveEventRepository

from .database_support import require_database


@pytest.fixture
async def db():
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


async def test_answers_to_question_keys_by_user_id_and_excludes_non_respondents(
    db: AsyncSession,
) -> None:
    lecturer = User(name="Lecturer", role="lecturer", email=f"l-{uuid.uuid4()}@example.com")
    answered_user = User(name="Answered", role="student", email=f"a-{uuid.uuid4()}@example.com")
    silent_user = User(name="Silent", role="student", email=f"s-{uuid.uuid4()}@example.com")
    course = Course(code=f"LIVE-{uuid.uuid4().hex[:8]}", name="Live Answers")
    db.add_all([lecturer, answered_user, silent_user, course])
    await db.flush()

    answered_student = Student(
        user_id=answered_user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    silent_student = Student(
        user_id=silent_user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    session = Session(
        instructor_id=lecturer.user_id,
        course_id=course.id,
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC) + timedelta(hours=1),
        mode="live",
        status="active",
    )
    db.add_all([answered_student, silent_student, session])
    await db.flush()

    material = Material(
        course_id=course.id,
        uploaded_by_user_id=lecturer.user_id,
        filename="live.pdf",
        content_type="application/pdf",
        size_bytes=10,
        status="completed",
    )
    db.add(material)
    await db.flush()

    question = Question(
        source_material_id=material.id,
        session_id=session.session_id,
        question_text="Which is correct?",
        question_type="mcq",
        status="delivered",
        difficulty="medium",
        options=["Wrong", "Right"],
        correct_option=1,
    )
    other_question = Question(
        source_material_id=material.id,
        session_id=session.session_id,
        question_text="A different question",
        question_type="mcq",
        status="delivered",
        difficulty="medium",
        options=["Wrong", "Right"],
        correct_option=1,
    )
    db.add_all([question, other_question])
    await db.flush()

    repository = LiveEventRepository(db)
    now = datetime.now(UTC)

    await repository.record_response(
        session_id=session.session_id,
        question_id=question.question_id,
        user_id=answered_user.user_id,
        selected_option=1,
        free_text=None,
        is_correct=True,
        elapsed_ms=1000,
        submitted_at=now,
    )
    # A response to a different question must not show up in this question's answers.
    await repository.record_response(
        session_id=session.session_id,
        question_id=other_question.question_id,
        user_id=answered_user.user_id,
        selected_option=0,
        free_text=None,
        is_correct=False,
        elapsed_ms=500,
        submitted_at=now,
    )

    answers = await repository.answers_to_question(session.session_id, question.question_id)

    assert set(answers) == {answered_user.user_id}
    assert answers[answered_user.user_id].selected_option == 1
