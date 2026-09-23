import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.models.question import Question
from app.realtime.classroom import ClosedQuestion
from app.schemas.content import QuestionStatus
from app.schemas.events import QuestionCloseReason
from app.services.live_recorder import LiveCloseRecorder, LiveResponseRecorder


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


def make_closed(question, *, answered=(), eligible=()):
    answered = frozenset(answered)
    return ClosedQuestion(
        session_id=question.session_id,
        question_id=question.question_id,
        reason=QuestionCloseReason.WINDOW_ELAPSED,
        closed_at=datetime.now(UTC),
        eligible=frozenset(eligible) | answered,
        answered=answered,
    )


def make_close_recorder(question, answers, steps):
    """steps records the order things happened in, across every seam."""
    sent = []

    async def get_question(question_id):
        return question if question_id == question.question_id else None

    async def store_close(closed):
        steps.append("stored")

    async def get_answers(session_id, question_id):
        steps.append("read answers")
        return answers

    async def send_feedback(session_id, user_id, feedback):
        steps.append("revealed")
        sent.append((user_id, feedback))

    recorder = LiveCloseRecorder(
        get_question=get_question,
        store_close=store_close,
        get_answers=get_answers,
        send_feedback=send_feedback,
    )
    return recorder, sent


async def test_close_stores_then_reveals_the_answer_to_each_student_who_answered():
    question = make_delivered_question(session_id=uuid.uuid4(), correct_option=1)
    right, wrong, silent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    answers = {
        right: SimpleNamespace(selected_option=1, free_text=None),
        wrong: SimpleNamespace(selected_option=0, free_text=None),
    }
    steps = []
    recorder, sent = make_close_recorder(question, answers, steps)

    await recorder.record_close(make_closed(question, answered={right, wrong}, eligible={silent}))

    assert steps[0] == "stored"
    revealed = dict(sent)
    assert set(revealed) == {right, wrong}
    assert revealed[right].correct is True
    assert revealed[wrong].correct is False
    for feedback in revealed.values():
        assert feedback.question_id == question.question_id
        assert "Interconnected layers" in feedback.explanation
        assert feedback.source_slide == 4


async def test_close_reveals_nothing_to_a_student_the_classroom_refused():
    """A write that timed out can land after the student was told it was not
    saved. Their answer is stored, but they are not in closed.answered."""
    question = make_delivered_question(session_id=uuid.uuid4())
    refused = uuid.uuid4()
    answers = {refused: SimpleNamespace(selected_option=1, free_text=None)}
    recorder, sent = make_close_recorder(question, answers, [])

    await recorder.record_close(make_closed(question, eligible={refused}))

    assert sent == []


async def test_close_of_a_free_text_question_is_stored_without_a_reveal():
    question = make_delivered_question(session_id=uuid.uuid4())
    question.question_type = "free_text"
    question.options = None
    question.correct_option = None
    student = uuid.uuid4()
    answers = {student: SimpleNamespace(selected_option=None, free_text="Layers")}
    steps = []
    recorder, sent = make_close_recorder(question, answers, steps)

    await recorder.record_close(make_closed(question, answered={student}))

    assert steps == ["stored"]
    assert sent == []


async def test_close_skips_a_reveal_it_cannot_score_and_still_reveals_the_rest():
    question = make_delivered_question(session_id=uuid.uuid4())
    good, bad = uuid.uuid4(), uuid.uuid4()
    answers = {
        good: SimpleNamespace(selected_option=1, free_text=None),
        bad: SimpleNamespace(selected_option=99, free_text=None),
    }
    recorder, sent = make_close_recorder(question, answers, [])

    await recorder.record_close(make_closed(question, answered={good, bad}))

    assert [user for user, _ in sent] == [good]


async def test_a_failed_store_stops_the_reveal():
    question = make_delivered_question(session_id=uuid.uuid4())
    student = uuid.uuid4()
    recorder, sent = make_close_recorder(
        question, {student: SimpleNamespace(selected_option=1, free_text=None)}, []
    )

    async def broken_store(closed):
        raise RuntimeError("database down")

    recorder._store_close = broken_store

    with pytest.raises(RuntimeError):
        await recorder.record_close(make_closed(question, answered={student}))
    assert sent == []
