import uuid

import pytest

from app.core.errors import ValidationError
from app.models.question import Question
from app.services.scoring import (
    build_mcq_feedback,
    build_mcq_reveal,
    feedback_payload,
    score_mcq,
)


def make_question(
    *,
    question_type: str = "mcq",
    options: list[str] | None = None,
    correct_option: int | None = 1,
    source_slide: int | None = 4,
    source_excerpt: str | None = "Neural networks contain interconnected layers.",
) -> Question:
    return Question(
        question_id=uuid.uuid4(),
        source_material_id=uuid.uuid4(),
        question_text="What do neural networks contain?",
        question_type=question_type,
        status="approved",
        difficulty="medium",
        options=options
        if options is not None
        else ["Nodes", "Interconnected layers", "Tables", "Servers"],
        correct_option=correct_option,
        source_slide=source_slide,
        source_excerpt=source_excerpt,
    )


def test_correct_mcq_answer_is_scored_true():
    question = make_question(correct_option=1)

    result = score_mcq(question, 1)

    assert result.is_correct is True
    assert result.selected_option == 1
    assert result.correct_option == 1
    assert result.correct_answer == "Interconnected layers"
    assert result.source_slide == 4
    assert result.source_excerpt == "Neural networks contain interconnected layers."


def test_incorrect_mcq_answer_is_scored_false():
    question = make_question(correct_option=1)

    result = score_mcq(question, 0)

    assert result.is_correct is False
    assert result.correct_option == 1
    assert result.correct_answer == "Interconnected layers"


@pytest.mark.parametrize("selected_option", [-1, 4, 99])
def test_selected_option_outside_available_choices_is_rejected(selected_option: int):
    question = make_question()

    with pytest.raises(ValidationError):
        score_mcq(question, selected_option)


def test_non_mcq_question_is_rejected():
    question = make_question(question_type="free_text")

    with pytest.raises(ValidationError):
        score_mcq(question, 0)


def test_question_without_options_is_rejected():
    question = make_question(options=[])

    with pytest.raises(ValidationError):
        score_mcq(question, 0)


def test_question_without_correct_option_is_rejected():
    question = make_question(correct_option=None)

    with pytest.raises(ValidationError):
        score_mcq(question, 0)


def test_question_with_invalid_correct_option_is_rejected():
    question = make_question(correct_option=8)

    with pytest.raises(ValidationError):
        score_mcq(question, 0)


@pytest.mark.parametrize("selected_option", [True, False, "1", 1.0, None])
def test_non_integer_selected_option_is_rejected(selected_option):
    question = make_question()

    with pytest.raises(ValidationError):
        score_mcq(question, selected_option)


def test_question_without_source_slide_still_scores():
    question = make_question(correct_option=1, source_slide=None)

    result = score_mcq(question, 1)

    assert result.is_correct is True
    assert result.source_slide is None


def test_question_without_source_excerpt_still_scores():
    question = make_question(correct_option=1, source_excerpt=None)

    result = score_mcq(question, 1)

    assert result.is_correct is True
    assert result.source_excerpt is None


def test_feedback_omits_slide_reference_when_source_slide_missing():
    question = make_question(correct_option=1, source_slide=None)
    score = score_mcq(question, 1)

    feedback = build_mcq_feedback(score)

    assert feedback.is_correct is True
    assert "slide" not in feedback.message.lower()


def test_correct_answer_builds_grounded_feedback():
    question = make_question(correct_option=1)
    score = score_mcq(question, 1)

    feedback = build_mcq_feedback(score)

    assert feedback.is_correct is True
    assert "Correct" in feedback.message
    assert feedback.source_slide == 4
    assert feedback.source_excerpt == "Neural networks contain interconnected layers."


def test_incorrect_immediate_feedback_withholds_correct_answer():
    question = make_question(correct_option=1)
    score = score_mcq(question, 0)

    feedback = build_mcq_feedback(score)

    assert feedback.is_correct is False
    assert "Interconnected layers" not in feedback.message
    assert feedback.source_slide == 4


def test_incorrect_reveal_feedback_includes_correct_answer():
    question = make_question(correct_option=1)
    score = score_mcq(question, 0)

    feedback = build_mcq_reveal(score)

    assert feedback.is_correct is False
    assert "Interconnected layers" in feedback.message
    assert feedback.source_slide == 4


def test_grounded_feedback_converts_to_live_event_payload():
    question = make_question(correct_option=1)
    score = score_mcq(question, 1)
    feedback = build_mcq_feedback(score)

    payload = feedback_payload(question.question_id, feedback)

    assert payload.question_id == question.question_id
    assert payload.correct is True
    assert payload.explanation == "Correct. See slide/page 4 for the supporting material."
    assert payload.source_slide == 4
