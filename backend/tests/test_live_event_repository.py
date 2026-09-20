"""Database tests for BBIS live-session persistence."""

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
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


async def test_live_events_are_stored_and_retrievable_by_session(
    db: AsyncSession,
) -> None:
    lecturer = User(
        name="Live Lecturer",
        role="lecturer",
        email=f"lecturer-{uuid.uuid4()}@example.com",
    )
    first_user = User(
        name="First Student",
        role="student",
        email=f"student-{uuid.uuid4()}@example.com",
    )
    second_user = User(
        name="Second Student",
        role="student",
        email=f"student-{uuid.uuid4()}@example.com",
    )
    course = Course(
        code=f"LIVE-{uuid.uuid4().hex[:8]}",
        name="Live Persistence",
    )
    db.add_all([lecturer, first_user, second_user, course])
    await db.flush()

    first_student = Student(
        user_id=first_user.user_id,
        course_id=course.id,
        consent_status="granted",
        enrolled_at=date.today(),
    )
    second_student = Student(
        user_id=second_user.user_id,
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
    db.add_all([first_student, second_student, session])
    await db.flush()

    material = Material(
        course_id=course.id,
        uploaded_by_user_id=lecturer.user_id,
        filename="live-session.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        status="completed",
    )
    db.add(material)
    await db.flush()

    question = Question(
        source_material_id=material.id,
        session_id=session.session_id,
        question_text="Which option is correct?",
        question_type="mcq",
        status="delivered",
        difficulty="medium",
        options=["Incorrect", "Correct"],
        correct_option=1,
    )
    db.add(question)
    await db.flush()

    repository = LiveEventRepository(db)
    now = datetime.now(UTC)

    first_join = await repository.record_participant_join(
        session_id=session.session_id,
        user_id=first_user.user_id,
        joined_at=now,
    )
    reconnect = await repository.record_participant_join(
        session_id=session.session_id,
        user_id=first_user.user_id,
        joined_at=now + timedelta(seconds=5),
    )

    assert first_join is not None
    assert reconnect is not None
    assert reconnect.participant_id == first_join.participant_id
    assert reconnect.connection_count == 2

    delivery = await repository.record_question_delivery(
        session_id=session.session_id,
        question_id=question.question_id,
        delivered_at=now,
        closes_at=now + timedelta(seconds=30),
        window_seconds=30,
    )

    response = await repository.record_response(
        session_id=session.session_id,
        question_id=question.question_id,
        user_id=first_user.user_id,
        selected_option=1,
        free_text=None,
        is_correct=True,
        elapsed_ms=1200,
        submitted_at=now + timedelta(seconds=1),
    )
    duplicate = await repository.record_response(
        session_id=session.session_id,
        question_id=question.question_id,
        user_id=first_user.user_id,
        selected_option=1,
        free_text=None,
        is_correct=True,
        elapsed_ms=1200,
        submitted_at=now + timedelta(seconds=2),
    )

    assert response is not None
    assert duplicate is not None
    assert duplicate.response_id == response.response_id

    prompt = await repository.record_prompt_outcome(
        prompt_id=uuid.uuid4(),
        session_id=session.session_id,
        user_id=first_user.user_id,
        escalation=1,
        sent_at=now,
        expires_at=now + timedelta(seconds=20),
        result="acknowledged",
        responded_at=now + timedelta(seconds=2),
    )
    assert prompt is not None
    assert prompt.response_status == "acknowledged"

    activity = await repository.record_activity(
        session_id=session.session_id,
        actor_user_id=lecturer.user_id,
        event_type="question.delivered",
        details={"question_id": str(question.question_id)},
        occurred_at=now,
    )
    assert activity.session_id == session.session_id

    closed = await repository.close_question_delivery(
        session_id=session.session_id,
        question_id=question.question_id,
        eligible_user_ids={first_user.user_id, second_user.user_id},
        answered_user_ids={first_user.user_id},
        reason="window_elapsed",
        closed_at=now + timedelta(seconds=30),
    )

    assert closed is not None
    assert closed.delivery_id == delivery.delivery_id
    assert closed.eligible_count == 2
    assert closed.respondent_count == 1

    responses, total = await repository.list_responses(
        session_id=session.session_id,
        limit=20,
        offset=0,
    )
    counts = await repository.dashboard_counts(session.session_id)

    assert total == 1
    assert [item.response_id for item in responses] == [response.response_id]
    assert counts.participants == 1
    assert counts.delivered_questions == 1
    assert counts.responses == 1
    assert counts.missed_responses == 1
    assert counts.prompt_outcomes == 1
    assert counts.activities == 1

    left = await repository.record_participant_leave(
        session_id=session.session_id,
        user_id=first_user.user_id,
        left_at=now + timedelta(minutes=1),
    )
    assert left is not None
    assert left.left_at == now + timedelta(minutes=1)
