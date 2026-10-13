"""Own-student review authorization, persistence and neutral missing-data handling."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth.store import STUDENT_ID
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.schemas.common import Page
from app.schemas.student_review import ReviewEngagement, ReviewSession
from app.services import student_review as service
from tests.test_topic_difficulty import database, question  # noqa: F401


def test_missing_engagement_is_neutral():
    engagement = ReviewEngagement()
    assert engagement.score is None
    assert engagement.status == "unavailable"
    assert "not zero" in engagement.explanation


@pytest.mark.parametrize(
    "index, expected",
    [(0, "A"), (1, "B"), (-1, "Answer text unavailable"), (2, "Answer text unavailable")],
)
def test_selected_option_is_bounded(index, expected):
    assert (
        service.answer_text(
            SimpleNamespace(free_text=None, selected_option=index),
            SimpleNamespace(options=["A", "B"]),
        )
        == expected
    )


def test_free_text_is_returned_as_data():
    assert (
        service.answer_text(SimpleNamespace(free_text="<script>text</script>"), None)
        == "<script>text</script>"
    )


async def test_missing_or_nonmember_session_fails_closed():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(one_or_none=lambda: None)
    with pytest.raises(NotFoundError):
        await service.own_session(db, uuid4(), uuid4())


def test_query_is_scoped_to_user_and_ended_sessions():
    user = uuid4()
    compiled = service.sessions_query(user).compile()
    assert user in compiled.params.values()
    assert "ended" in compiled.params.values()
    assert "student.user_id =" in str(compiled)
    assert "student.course_id = session.course_id" in str(compiled)


def test_review_route_uses_identity_and_private_cache(as_student, app, monkeypatch):
    async def db_override():
        yield object()

    app.dependency_overrides[get_db] = db_override
    read = AsyncMock(return_value=Page[ReviewSession](items=[], total=0, limit=20, offset=0))
    monkeypatch.setattr(service, "list_reviews", read)
    result = as_student.get("/api/v1/student-reviews?limit=20")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert read.call_args.args[1] == STUDENT_ID


def test_staff_cannot_read_student_review(as_lecturer):
    assert as_lecturer.get("/api/v1/student-reviews").status_code == 403


def test_anonymous_cannot_read_student_review(client):
    assert client.get("/api/v1/student-reviews").status_code == 401


async def test_source_lookup_is_scoped_and_bounded(monkeypatch):
    user_id, session_id, student_id, response_id, material_id, course_id = [
        uuid4() for _ in range(6)
    ]
    monkeypatch.setattr(
        service,
        "own_session",
        AsyncMock(
            return_value=(
                SimpleNamespace(course_id=course_id),
                "CS101",
                student_id,
            )
        ),
    )
    q = SimpleNamespace(
        source_material_id=material_id, source_slide=4, source_excerpt="quoted text"
    )
    chunks = [
        (
            SimpleNamespace(chunk_id=uuid4(), source_page=4, chunk_text=f"quoted text {i}"),
            "Lecture.pdf",
        )
        for i in range(6)
    ]
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: q),
        SimpleNamespace(all=lambda: chunks),
    ]
    result = await service.read_sources(db, user_id, session_id, response_id)
    assert len(result.items) == 5
    assert result.has_more
    assert all(s.match == "excerpt" for s in result.items)
    answer_query, source_query = [call.args[0].compile() for call in db.execute.call_args_list]
    assert {student_id, session_id, response_id} <= set(answer_query.params.values())
    assert "student_response.student_id =" in str(answer_query)
    assert {material_id, course_id, 4, 6} <= set(source_query.params.values())
    assert "source_material.course_id =" in str(source_query)
    assert "rag_chunk.source_material_id =" in str(source_query)


async def test_no_source_locator_never_searches_arbitrary_material(monkeypatch):
    monkeypatch.setattr(
        service,
        "own_session",
        AsyncMock(
            return_value=(
                SimpleNamespace(course_id=uuid4()),
                "CS101",
                uuid4(),
            )
        ),
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(
            source_material_id=uuid4(),
            source_slide=None,
            source_excerpt="  ",
        )
    )
    result = await service.read_sources(db, uuid4(), uuid4(), uuid4())
    assert not result.items
    assert db.execute.await_count == 1


async def test_foreign_response_does_not_return_sources(monkeypatch):
    monkeypatch.setattr(
        service,
        "own_session",
        AsyncMock(
            return_value=(
                SimpleNamespace(course_id=uuid4()),
                "CS101",
                uuid4(),
            )
        ),
    )
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    with pytest.raises(NotFoundError):
        await service.read_sources(db, uuid4(), uuid4(), uuid4())
    assert db.execute.await_count == 1


async def test_database_review_is_own_ended_session_only(database, question):  # noqa: F811
    async with database() as db:
        with pytest.raises(NotFoundError):
            await service.own_session(db, question.user, question.session)
        session = await db.get(Session, question.session)
        session.status = "ended"
        student = (
            await db.execute(select(Student).where(Student.user_id == question.user))
        ).scalar_one()
        response = StudentResponse(
            session_id=question.session,
            student_id=student.student_id,
            question_id=question.question,
            selected_option=0,
            is_correct=False,
        )
        db.add(response)
        other_user = User(
            name="Other review student", role="student", email=f"{uuid4()}@example.test"
        )
        db.add(other_user)
        await db.flush()
        other_student = Student(
            user_id=other_user.user_id,
            course_id=session.course_id,
            consent_status="granted",
            enrolled_at=date.today(),
        )
        db.add(other_student)
        await db.flush()
        other_response = StudentResponse(
            session_id=question.session,
            student_id=other_student.student_id,
            question_id=question.question,
            selected_option=1,
            is_correct=True,
        )
        db.add(other_response)
        await db.flush()
        result = await service.read_review(db, question.user, question.session, 20, 0)
        assert result.questions_attempted == 1
        assert result.answers[0].answer == "Incorrect"
        assert result.answers[0].is_correct is False
        assert result.engagement.score is None
        assert result.total == 1
        with pytest.raises(NotFoundError):
            await service.read_review(db, uuid4(), question.session, 20, 0)
        with pytest.raises(NotFoundError):
            await service.read_sources(db, question.user, question.session, uuid4())
        with pytest.raises(NotFoundError):
            await service.read_sources(
                db, question.user, question.session, other_response.response_id
            )
        assert not (await service.read_review(db, question.user, question.session, 20, 20)).answers
        # Only this question's material and source page can be returned.
        q = await db.get(Question, question.question)
        q.source_slide = 4
        db.add_all(
            [
                RagChunk(
                    source_material_id=question.material,
                    chunk_index=0,
                    source_page=4,
                    chunk_text="Relevant source",
                ),
                RagChunk(
                    source_material_id=question.material,
                    chunk_index=1,
                    source_page=5,
                    chunk_text="Other page",
                ),
            ]
        )
        await db.flush()
        sources = await service.read_sources(
            db, question.user, question.session, response.response_id
        )
        assert [s.text for s in sources.items] == ["Relevant source"]
        assert sources.items[0].match == "page"
        await db.rollback()
