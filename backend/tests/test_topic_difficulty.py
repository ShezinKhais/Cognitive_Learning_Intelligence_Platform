"""Topic difficulty: which topics a class found hard, from its answers' labels."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
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
from app.repositories import topic_difficulty_repository
from app.repositories.topic_difficulty_repository import DatabaseTopicAnswers
from app.schemas.content import Difficulty
from app.services import live_wiring
from app.services.topic_difficulty import (
    MIN_ANSWERS,
    NO_TOPIC,
    LabelledAnswer,
    latest_answers,
    level_for,
    topic_difficulty,
)

from .database_support import require_database


def answers(topic, labels, *, question="q1", confidence=1.0, difficulty="medium"):
    """One answer per label, each from a different student."""
    return [
        LabelledAnswer(
            student_id=f"s{i}",
            question_id=question,
            topic=topic,
            label=label,
            confidence=confidence,
            question_difficulty=difficulty,
        )
        for i, label in enumerate(labels)
    ]


@pytest.mark.parametrize(
    "score, level",
    [
        (0.0, Difficulty.EASY),
        (0.32, Difficulty.EASY),
        (0.33, Difficulty.MEDIUM),
        (0.65, Difficulty.MEDIUM),
        (0.66, Difficulty.HARD),
        (1.0, Difficulty.HARD),
    ],
)
def test_levels_are_three_slices(score, level):
    assert level_for(score) is level


def test_the_score_weighs_partial_as_half():
    [topic] = topic_difficulty(
        answers("Odds ratios", ["mastered", "partial", "partial", "struggling", "struggling"])
    )

    assert (topic.mastered, topic.partial, topic.struggling) == (1, 2, 2)
    assert topic.score == pytest.approx(0.6)
    assert topic.level is Difficulty.MEDIUM


def test_too_few_answers_get_no_level():
    [topic] = topic_difficulty(answers("Odds ratios", ["struggling"] * (MIN_ANSWERS - 1)))

    assert topic.answers == MIN_ANSWERS - 1
    assert topic.score is None and topic.level is None


def test_topics_are_ranked_hardest_first_with_unrated_last():
    ranked = topic_difficulty(
        answers("Easy", ["mastered"] * 5, question="e")
        + answers("Few", ["struggling"] * 2, question="f")
        + answers("Hard", ["struggling"] * 5, question="h")
        + answers("Middle", ["partial"] * 5, question="m")
    )

    assert [t.topic for t in ranked] == ["Hard", "Middle", "Easy", "Few"]


def test_spelling_and_spacing_of_a_topic_do_not_split_it():
    [topic] = topic_difficulty(
        answers("Odds  ratios", ["mastered"] * 3, question="a")
        + answers(" odds ratios", ["struggling"] * 3, question="b")
    )

    assert topic.topic == "Odds ratios"
    assert (topic.questions, topic.answers) == (2, 6)


def test_answers_without_a_topic_are_grouped_together():
    [topic] = topic_difficulty(
        answers(None, ["mastered"] * 3, question="a")
        + answers("  ", ["mastered"] * 3, question="b")
    )

    assert topic.topic == NO_TOPIC
    assert topic.answers == 6


def test_a_relabelled_answer_counts_once_by_its_newest_label():
    first = answers("Odds ratios", ["struggling"])[0]
    newer = LabelledAnswer(**{**first.__dict__, "label": "mastered"})

    assert latest_answers([first, newer]) == [newer]
    [topic] = topic_difficulty([first, newer])
    assert (topic.answers, topic.mastered, topic.struggling) == (1, 1, 0)


def test_unknown_labels_are_not_counted():
    [topic] = topic_difficulty(answers("Odds ratios", ["mastered", "pending", "struggling"]))

    assert topic.answers == 2


def test_no_answers_means_no_topics():
    assert topic_difficulty([]) == []


def test_uncertain_labels_are_counted_in_full_and_reported():
    sure = answers("Odds ratios", ["mastered"] * 3, question="a")
    unsure = answers("Odds ratios", ["struggling"] * 2, question="b", confidence=0.45)

    [topic] = topic_difficulty(sure + unsure)

    assert topic.uncertain == 2
    assert topic.score == pytest.approx(0.4)


def test_the_generators_guess_is_kept_beside_how_the_class_did():
    [topic] = topic_difficulty(
        answers("Odds ratios", ["struggling"] * 3, question="a", difficulty="easy")
        + answers("Odds ratios", ["struggling"] * 3, question="b", difficulty="easy")
        + answers("Odds ratios", ["partial"] * 3, question="c", difficulty="hard")
    )

    assert topic.expected is Difficulty.EASY
    assert topic.level is Difficulty.HARD


def test_an_even_split_of_guesses_has_no_expected_level():
    [topic] = topic_difficulty(
        answers("Odds ratios", ["mastered"] * 3, question="a", difficulty="easy")
        + answers("Odds ratios", ["mastered"] * 3, question="b", difficulty="hard")
    )

    assert topic.expected is None


@pytest.fixture
async def database(monkeypatch):
    require_database()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(live_wiring, "get_session_factory", lambda: factory)
    monkeypatch.setattr(topic_difficulty_repository, "get_session_factory", lambda: factory)
    yield factory
    await engine.dispose()


@pytest.fixture
async def question(database):
    """A delivered MCQ on "Neural networks" in a live session, and a student.
    Everything it creates is removed afterwards."""
    async with database() as db:
        lecturer = User(
            name="Topic Lecturer", role="lecturer", email=f"lecturer-{uuid.uuid4()}@example.com"
        )
        student_user = User(
            name="Topic Student", role="student", email=f"student-{uuid.uuid4()}@example.com"
        )
        course = Course(code=f"TD-{uuid.uuid4().hex[:8]}", name="Topic Difficulty")
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
            filename="topics.pdf",
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
            difficulty="easy",
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


async def test_a_sessions_labelled_answers_are_read_with_their_topic(database, question):
    await live_wiring._store_response(
        session_id=question.session,
        question_id=question.question,
        user_id=question.user,
        selected_option=0,
        free_text=None,
        is_correct=False,
        elapsed_ms=900,
    )

    [topic] = await DatabaseTopicAnswers().session_topics(question.session)

    assert topic.topic == "Neural networks"
    assert (topic.answers, topic.struggling) == (1, 1)
    assert topic.expected is Difficulty.EASY
    # One answer is not enough to call the topic hard.
    assert topic.level is None


async def test_another_sessions_answers_are_not_read(database, question):
    assert await DatabaseTopicAnswers().session_answers(uuid.uuid4()) == []
