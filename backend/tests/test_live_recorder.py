import uuid

import pytest

from app.core.errors import NotFoundError
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


class _Submission:
    def __init__(self, *, session_id, question_id, user_id, selected_option=None, free_text=None):
        self.session_id = session_id
        self.question_id = question_id
        self.user_id = user_id
        self.selected_option = selected_option
        self.free_text = free_text


async def test_record_scores_and_publishes_mcq_feedback():
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id, correct_option=1)

    async def get_question(question_id):
        assert question_id == question.question_id
        return question

    published = []

    async def publish_feedback(sid, uid, feedback):
        published.append((sid, uid, feedback))

    recorder = LiveResponseRecorder(get_question=get_question, publish_feedback=publish_feedback)
    submission = _Submission(
        session_id=session_id,
        question_id=question.question_id,
        user_id=user_id,
        selected_option=1,
    )

    await recorder.record(submission)

    assert len(published) == 1
    sid, uid, feedback = published[0]
    assert sid == session_id
    assert uid == user_id
    assert feedback.correct is True


async def test_record_raises_when_question_missing():
    async def get_question(question_id):
        return None

    async def publish_feedback(sid, uid, feedback):
        raise AssertionError("should not publish when the question is missing")

    recorder = LiveResponseRecorder(get_question=get_question, publish_feedback=publish_feedback)
    submission = _Submission(
        session_id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        selected_option=1,
    )

    with pytest.raises(NotFoundError):
        await recorder.record(submission)
