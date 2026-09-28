import uuid

import pytest

from app.models.comprehension_result import ComprehensionResult
from app.schemas.events import FeedbackResultPayload
from app.schemas.session import ComprehensionLabel
from app.services import comprehension_writer
from app.services.comprehension_writer import mcq_label, store_comprehension


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
