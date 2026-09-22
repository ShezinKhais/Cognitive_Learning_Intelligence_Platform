import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.models.question import Question
from app.schemas.content import QuestionStatus
from app.services.live_recorder import LiveResponseRecorder


def make_delivered_question(*, session_id: uuid.UUID, correct_option: int = 1) -> Question:
    return Question(
        question_id=uuid.uuid4(),
        source_material_id=uuid.uuid4(),
        session_id=session_id,
        question_text="What do neural networks contain?",
        question_type="mcq",
        status=QuestionStatus.DELIVERED.value,
        difficulty="medium",
        options=["Nodes", "Interconnected layers", "Tables", "Servers"],
        correct_option=correct_option,
        source_slide=4,
        source_excerpt="Neural networks contain interconnected layers.",
    )


def make_submission(*, session_id, question_id, user_id=None, selected_option=None, free_text=None):
    return SimpleNamespace(
        session_id=session_id,
        question_id=question_id,
        user_id=user_id or uuid.uuid4(),
        selected_option=selected_option,
        free_text=free_text,
        client_elapsed_ms=1200,
        received_at=datetime.now(UTC),
    )


class FakeStore:
    """Idempotent per (session, question, user), like record_response."""

    def __init__(self):
        self.rows = {}
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        key = (kwargs["session_id"], kwargs["question_id"], kwargs["user_id"])
        return self.rows.setdefault(key, SimpleNamespace(**kwargs))


def make_recorder(question, store):
    async def get_question(question_id):
        return question if question is not None and question_id == question.question_id else None

    return LiveResponseRecorder(get_question=get_question, store_response=store)


async def test_record_scores_stores_and_returns_mcq_feedback():
    session_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id, correct_option=1)
    store = FakeStore()
    submission = make_submission(
        session_id=session_id, question_id=question.question_id, selected_option=1
    )

    feedback = await make_recorder(question, store).record(submission)

    assert feedback.correct is True
    assert feedback.question_id == question.question_id
    assert len(store.calls) == 1
    stored = store.calls[0]
    assert stored["user_id"] == submission.user_id
    assert stored["selected_option"] == 1
    assert stored["free_text"] is None
    assert stored["is_correct"] is True
    assert stored["elapsed_ms"] == 1200
    assert stored["submitted_at"] == submission.received_at


async def test_record_stores_free_text_unscored():
    session_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id)
    store = FakeStore()
    submission = make_submission(
        session_id=session_id, question_id=question.question_id, free_text="Layers"
    )

    feedback = await make_recorder(question, store).record(submission)

    assert feedback.correct is None
    assert store.calls[0]["free_text"] == "Layers"
    assert store.calls[0]["is_correct"] is None


async def test_retry_after_landed_write_returns_feedback_for_stored_answer():
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id, correct_option=1)
    store = FakeStore()
    recorder = make_recorder(question, store)

    await recorder.record(
        make_submission(
            session_id=session_id,
            question_id=question.question_id,
            user_id=user_id,
            selected_option=1,
        )
    )
    feedback = await recorder.record(
        make_submission(
            session_id=session_id,
            question_id=question.question_id,
            user_id=user_id,
            selected_option=0,
        )
    )

    assert len(store.rows) == 1
    assert feedback.correct is True


async def test_record_does_not_store_when_scoring_refuses():
    question = make_delivered_question(session_id=uuid.uuid4())
    store = FakeStore()
    submission = make_submission(
        session_id=uuid.uuid4(), question_id=question.question_id, selected_option=1
    )

    with pytest.raises(ValidationError):
        await make_recorder(question, store).record(submission)

    assert store.calls == []


async def test_record_raises_when_question_missing():
    store = FakeStore()
    submission = make_submission(
        session_id=uuid.uuid4(), question_id=uuid.uuid4(), selected_option=1
    )

    with pytest.raises(NotFoundError):
        await make_recorder(None, store).record(submission)

    assert store.calls == []
