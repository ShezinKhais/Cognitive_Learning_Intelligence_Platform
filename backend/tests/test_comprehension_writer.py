"""AI 1's comprehension label, written with the answer it describes.

The label goes through live_wiring's store, as a live answer does, against a
real database, and is read back by Cyber 1's source for the class
comprehension alert.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.comprehension_result import ComprehensionResult
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.repositories import comprehension_repository
from app.repositories.comprehension_repository import DatabaseComprehensionSource
from app.schemas.session import ComprehensionLabel
from app.services import live_wiring
from app.services.comprehension_writer import label_response, mcq_label

from .database_support import require_database


def test_mcq_labels():
    assert mcq_label(True) is ComprehensionLabel.MASTERED
    assert mcq_label(False) is ComprehensionLabel.STRUGGLING


@pytest.fixture
async def database(monkeypatch):
    """A committed-write session factory, installed where the live store and
    Cyber 1's reader look for one."""
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(live_wiring, "get_session_factory", lambda: factory)
    monkeypatch.setattr(comprehension_repository, "get_session_factory", lambda: factory)
    yield factory
    await engine.dispose()


@pytest.fixture
async def question(database):
    """A delivered MCQ in a live session, whose correct option is 1, and the
    student answering it. Everything it creates is removed afterwards."""
    async with database() as db:
        lecturer = User(
            name="Writer Lecturer", role="lecturer", email=f"lecturer-{uuid.uuid4()}@example.com"
        )
        student_user = User(
            name="Writer Student", role="student", email=f"student-{uuid.uuid4()}@example.com"
        )
        course = Course(code=f"CW-{uuid.uuid4().hex[:8]}", name="Comprehension Writer")
        db.add_all([lecturer, student_user, course])
        await db.flush()
        session = Session(
            instructor_id=lecturer.user_id,
            course_id=course.id,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC) + timedelta(hours=1),
            mode="live",
            status="active",
        )
        material = Material(
            course_id=course.id,
            uploaded_by_user_id=lecturer.user_id,
            filename="writer.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            status="completed",
        )
        db.add_all(
            [
                Student(
                    user_id=student_user.user_id,
                    course_id=course.id,
                    consent_status="granted",
                    enrolled_at=date.today(),
                ),
                session,
                material,
            ]
        )
        await db.flush()
        mcq = Question(
            source_material_id=material.id,
            session_id=session.session_id,
            question_text="Which option is correct?",
            question_type="mcq",
            status="delivered",
            difficulty="medium",
            topic="Neural networks",
            options=["Incorrect", "Correct"],
            correct_option=1,
        )
        db.add(mcq)
        await db.commit()
        ids = SimpleNamespace(
            session=session.session_id,
            question=mcq.question_id,
            user=student_user.user_id,
            material=material.id,
            course=course.id,
            users=[lecturer.user_id, student_user.user_id],
        )

    yield ids

    async with database() as db:
        responses = select(StudentResponse.response_id).where(
            StudentResponse.question_id == ids.question
        )
        await db.execute(
            delete(ComprehensionResult).where(ComprehensionResult.response_id.in_(responses))
        )
        await db.execute(delete(StudentResponse).where(StudentResponse.question_id == ids.question))
        await db.execute(delete(Question).where(Question.question_id == ids.question))
        await db.execute(delete(Session).where(Session.session_id == ids.session))
        await db.execute(delete(Material).where(Material.id == ids.material))
        await db.execute(delete(Student).where(Student.course_id == ids.course))
        await db.execute(delete(Course).where(Course.id == ids.course))
        await db.execute(delete(User).where(User.user_id.in_(ids.users)))
        await db.commit()


def answer(ids, *, selected_option=None, free_text=None, is_correct=None):
    """What LiveResponseRecorder hands the store for one submission."""
    return {
        "session_id": ids.session,
        "question_id": ids.question,
        "user_id": ids.user,
        "selected_option": selected_option,
        "free_text": free_text,
        "is_correct": is_correct,
        "elapsed_ms": 900,
    }


async def labels_for(database, response_id):
    async with database() as db:
        rows = await db.execute(
            select(ComprehensionResult).where(ComprehensionResult.response_id == response_id)
        )
        return list(rows.scalars())


@pytest.mark.parametrize(
    "selected, correct, label, score",
    [(1, True, "mastered", 1.0), (0, False, "struggling", 0.0)],
)
async def test_a_scored_answer_is_stored_with_its_label(
    database, question, selected, correct, label, score
):
    stored = await live_wiring._store_response(
        **answer(question, selected_option=selected, is_correct=correct)
    )

    [row] = await labels_for(database, stored.response_id)
    assert (row.label, row.score, row.confidence_score) == (label, score, 1.0)


async def test_the_label_reaches_the_comprehension_alert(database, question):
    await live_wiring._store_response(**answer(question, selected_option=1, is_correct=True))

    found = await DatabaseComprehensionSource().question_labels(question.session, question.question)

    assert found.labels == ["mastered"]
    assert found.topic == "Neural networks"


async def test_free_text_is_stored_without_a_label(database, question):
    stored = await live_wiring._store_response(**answer(question, free_text="Layers of nodes."))

    assert await labels_for(database, stored.response_id) == []


async def test_a_retry_keeps_the_label_of_the_answer_already_stored(database, question):
    first = await live_wiring._store_response(
        **answer(question, selected_option=1, is_correct=True)
    )
    retried = await live_wiring._store_response(
        **answer(question, selected_option=0, is_correct=False)
    )

    assert retried.response_id == first.response_id
    [row] = await labels_for(database, first.response_id)
    assert row.label == "mastered"


async def test_an_answer_whose_label_fails_is_not_stored_either(database, question, monkeypatch):
    async def failing_label(db, response):
        raise RuntimeError("comprehension_result is unavailable")

    monkeypatch.setattr(live_wiring, "label_response", failing_label)

    with pytest.raises(RuntimeError):
        await live_wiring._store_response(**answer(question, selected_option=1, is_correct=True))

    async with database() as db:
        stored = await db.scalar(
            select(func.count()).where(StudentResponse.question_id == question.question)
        )
    assert stored == 0


async def test_two_labels_written_at_once_leave_one(database, question):
    stored = await live_wiring._store_response(**answer(question, free_text="Layers of nodes."))
    # Free text is unlabelled, so these two are the only writers.
    stored.is_correct = True

    async def label_in_own_transaction():
        async with database() as db:
            await label_response(db, stored)
            await asyncio.sleep(0.05)
            await db.commit()

    await asyncio.gather(label_in_own_transaction(), label_in_own_transaction())

    assert len(await labels_for(database, stored.response_id)) == 1
