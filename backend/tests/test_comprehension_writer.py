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
from app.repositories.live_event_repository import LiveEventRepository
from app.schemas.events import FeedbackResultPayload
from app.schemas.session import ComprehensionLabel
from app.services import comprehension_writer
from app.services.comprehension_writer import mcq_label, store_comprehension

from .database_support import require_database


class FakeSession:
    """Holds labelled rows by response id, as comprehension_result would."""

    def __init__(self, rows):
        self.rows = rows
        self.pending = []
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def scalar(self, statement):
        response_id = statement.whereclause.right.value
        row = self.rows.get(response_id)
        return row.result_id if row is not None else None

    def add(self, row):
        self.pending.append(row)

    async def commit(self):
        for row in self.pending:
            row.result_id = uuid.uuid4()
            self.rows[row.response_id] = row
        self.pending.clear()

    async def rollback(self):
        self.rolled_back = True
        self.pending.clear()


@pytest.fixture
def rows(monkeypatch):
    stored: dict[uuid.UUID, ComprehensionResult] = {}
    monkeypatch.setattr(
        comprehension_writer, "get_session_factory", lambda: lambda: FakeSession(stored)
    )
    return stored


def test_mcq_labels():
    assert mcq_label(True) is ComprehensionLabel.MASTERED
    assert mcq_label(False) is ComprehensionLabel.STRUGGLING


@pytest.mark.parametrize(
    "correct, label, score",
    [(True, "mastered", 1.0), (False, "struggling", 0.0)],
)
async def test_stores_the_label_for_an_mcq_answer(rows, correct, label, score):
    response_id = uuid.uuid4()
    feedback = FeedbackResultPayload(
        question_id=uuid.uuid4(), correct=correct, explanation="See slide 4."
    )

    await store_comprehension(response_id, feedback)

    row = rows[response_id]
    assert row.label == label
    assert row.score == score
    assert row.confidence_score == 1.0
    assert row.ai_feedback_text == "See slide 4."


async def test_a_retried_answer_is_labelled_once(rows):
    response_id = uuid.uuid4()
    first = FeedbackResultPayload(question_id=uuid.uuid4(), correct=True)

    await store_comprehension(response_id, first)
    kept = rows[response_id]
    await store_comprehension(response_id, first.model_copy(update={"correct": False}))

    assert rows[response_id] is kept
    assert kept.label == "mastered"
    assert kept.ai_feedback_text == ""


async def test_unscored_free_text_is_not_labelled(rows):
    await store_comprehension(
        uuid.uuid4(), FeedbackResultPayload(question_id=uuid.uuid4(), correct=None)
    )

    assert rows == {}


@pytest.fixture
async def database(monkeypatch):
    """A committed-write session factory, installed where the writer and
    Cyber 1's reader look for one."""
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(comprehension_writer, "get_session_factory", lambda: factory)
    monkeypatch.setattr(comprehension_repository, "get_session_factory", lambda: factory)
    yield factory
    await engine.dispose()


async def test_a_stored_label_reaches_the_comprehension_alert(database):
    """The whole path on a real database: the answer is stored, labelled once,
    and read back by the source the class comprehension alert uses."""
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
        student = Student(
            user_id=student_user.user_id,
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
        material = Material(
            course_id=course.id,
            uploaded_by_user_id=lecturer.user_id,
            filename="writer.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            status="completed",
        )
        db.add_all([student, session, material])
        await db.flush()
        question = Question(
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
        db.add(question)
        await db.flush()
        response = await LiveEventRepository(db).record_response(
            session_id=session.session_id,
            question_id=question.question_id,
            user_id=student_user.user_id,
            selected_option=1,
            free_text=None,
            is_correct=True,
            elapsed_ms=900,
        )
        await db.commit()
        ids = SimpleNamespace(
            response=response.response_id,
            session=session.session_id,
            question=question.question_id,
            material=material.id,
            course=course.id,
            users=[lecturer.user_id, student_user.user_id],
        )

    try:
        feedback = FeedbackResultPayload(question_id=ids.question, correct=True)
        await store_comprehension(ids.response, feedback)
        await store_comprehension(ids.response, feedback)

        found = await DatabaseComprehensionSource().question_labels(ids.session, ids.question)
        assert found.labels == ["mastered"]
        assert found.topic == "Neural networks"

        async with database() as db:
            count = await db.scalar(
                select(func.count()).where(ComprehensionResult.response_id == ids.response)
            )
        assert count == 1
    finally:
        async with database() as db:
            await db.execute(
                delete(ComprehensionResult).where(ComprehensionResult.response_id == ids.response)
            )
            await db.execute(
                delete(StudentResponse).where(StudentResponse.response_id == ids.response)
            )
            await db.execute(delete(Question).where(Question.question_id == ids.question))
            await db.execute(delete(Session).where(Session.session_id == ids.session))
            await db.execute(delete(Material).where(Material.id == ids.material))
            await db.execute(delete(Student).where(Student.course_id == ids.course))
            await db.execute(delete(Course).where(Course.id == ids.course))
            await db.execute(delete(User).where(User.user_id.in_(ids.users)))
            await db.commit()
