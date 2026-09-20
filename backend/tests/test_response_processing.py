import uuid

import pytest

from app.core.errors import ValidationError
from app.models.question import Question
from app.schemas.content import QuestionStatus
from app.services.response_processing import (
    process_mcq_submission,
    process_submission,
)


def make_delivered_question(
    *,
    session_id=None,
    status: str = QuestionStatus.DELIVERED.value,
    correct_option: int = 1,
) -> Question:
    session_id = session_id or uuid.uuid4()

    return Question(
        question_id=uuid.uuid4(),
        source_material_id=uuid.uuid4(),
        session_id=session_id,
        question_text="What do neural networks contain?",
        question_type="mcq",
        status=status,
        difficulty="medium",
        options=[
            "Nodes",
            "Interconnected layers",
            "Tables",
            "Servers",
        ],
        correct_option=correct_option,
        source_slide=4,
        source_excerpt="Neural networks contain interconnected layers.",
    )


def test_process_mcq_submission_returns_correct_feedback():
    session_id = uuid.uuid4()
    question = make_delivered_question(
        session_id=session_id,
        correct_option=1,
    )

    payload = process_mcq_submission(
        session_id=session_id,
        question=question,
        selected_option=1,
    )

    assert payload.question_id == question.question_id
    assert payload.correct is True
    assert payload.explanation == (
        "Correct. See slide/page 4 for the supporting material."
    )
    assert payload.source_slide == 4


def test_process_mcq_submission_returns_incorrect_feedback():
    session_id = uuid.uuid4()
    question = make_delivered_question(
        session_id=session_id,
        correct_option=1,
    )

    payload = process_mcq_submission(
        session_id=session_id,
        question=question,
        selected_option=0,
    )

    assert payload.correct is False
    assert "Interconnected layers" in payload.explanation
    assert payload.source_slide == 4


def test_process_mcq_submission_rejects_question_from_another_session():
    question = make_delivered_question()

    with pytest.raises(ValidationError):
        process_mcq_submission(
            session_id=uuid.uuid4(),
            question=question,
            selected_option=1,
        )


def test_process_mcq_submission_rejects_question_not_yet_delivered():
    session_id = uuid.uuid4()
    question = make_delivered_question(
        session_id=session_id,
        status=QuestionStatus.STAGED.value,
    )

    with pytest.raises(ValidationError):
        process_mcq_submission(
            session_id=session_id,
            question=question,
            selected_option=1,
        )

def test_process_submission_routes_mcq_to_mcq_processor():
    session_id = uuid.uuid4()
    question = make_delivered_question(
        session_id=session_id,
        correct_option=1,
    )

    payload = process_submission(
        session_id=session_id,
        question=question,
        selected_option=1,
    )

    assert payload.question_id == question.question_id
    assert payload.correct is True
    assert payload.source_slide == 4


def test_process_submission_rejects_missing_answer():
    session_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id)

    with pytest.raises(ValidationError):
        process_submission(
            session_id=session_id,
            question=question,
        )


def test_process_submission_rejects_both_answer_types():
    session_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id)

    with pytest.raises(ValidationError):
        process_submission(
            session_id=session_id,
            question=question,
            selected_option=1,
            free_text="Interconnected layers",
        )


def test_process_submission_reserves_free_text_for_classifier():
    session_id = uuid.uuid4()
    question = make_delivered_question(session_id=session_id)

    with pytest.raises(ValidationError):
        process_submission(
            session_id=session_id,
            question=question,
            free_text="Interconnected layers",
        )
