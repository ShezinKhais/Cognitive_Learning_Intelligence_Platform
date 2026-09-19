"""Pure-logic tests for Phase 3 scoring and engagement.

Owners: AI 1 (scoring), Cyber 1 (engagement, alerts). No database or app
fixture needed -- these are plain functions.
"""

import uuid

from app.models.question import Question
from app.schemas.events import AttentionSignalPayload
from app.schemas.session import EngagementStatus
from app.services.engagement import (
    compute_engagement,
    evaluate_comprehension_alert,
    should_send_dynamic_prompt,
)
from app.services.scoring import classify_free_text, score_mcq


def _mcq(correct_option: int = 0, options=("Paris", "Lyon", "Marseille")) -> Question:
    return Question(
        question_id=uuid.uuid4(),
        source_material_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        question_text="What is the capital of France?",
        question_type="mcq",
        status="delivered",
        difficulty="medium",
        options=list(options),
        correct_option=correct_option,
        source_slide=4,
    )


def test_score_mcq_correct_answer():
    scored = score_mcq(_mcq(correct_option=0), selected_option=0)
    assert scored.correct is True
    assert scored.source_slide == 4


def test_score_mcq_wrong_answer_names_the_right_one():
    scored = score_mcq(_mcq(correct_option=0), selected_option=1)
    assert scored.correct is False
    assert "Paris" in scored.explanation


def test_classify_free_text_never_claims_correctness_yet():
    question = _mcq()
    question.question_type = "free_text"
    question.options = None
    question.correct_option = None
    scored = classify_free_text(question, "some answer")
    assert scored.correct is None


def test_compute_engagement_with_no_signals_is_insufficient_data():
    result = compute_engagement(None, None)
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert result.score is None
    assert result.signals_available == []


def test_compute_engagement_attempt_rate_alone_is_just_enough_confidence():
    result = compute_engagement(0.8, None)
    assert result.status == EngagementStatus.ENGAGED
    assert result.signals_available == ["attempt_rate"]
    assert result.confidence == 0.25


def test_compute_engagement_low_attempt_rate_is_disengaged():
    result = compute_engagement(0.1, None)
    assert result.status == EngagementStatus.DISENGAGED


def test_compute_engagement_renormalises_missing_signals():
    """Only gaze reported (no face/speaking) still yields a full-confidence
    read once attempt_rate is added -- the missing components are dropped
    from the average rather than counted as zero."""
    attention = AttentionSignalPayload(gaze_on_screen_ratio=0.9, window_seconds=5.0)
    result = compute_engagement(0.9, attention)
    assert result.signals_available == ["attempt_rate", "gaze"]
    assert result.score == 0.9
    assert result.status == EngagementStatus.ENGAGED


def test_compute_engagement_zero_signals_never_reports_disengaged():
    """No evidence at all must render as insufficient data, never as a
    confident disengagement call -- see EngagementOut's own docstring."""
    result = compute_engagement(None, None)
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert result.status != EngagementStatus.DISENGAGED


def test_should_send_dynamic_prompt_never_fires_on_insufficient_data():
    result = compute_engagement(None, None)
    assert not should_send_dynamic_prompt(result, prompts_already_sent=0, max_per_student=3)


def test_should_send_dynamic_prompt_fires_when_at_risk():
    result = compute_engagement(0.2, None)
    assert should_send_dynamic_prompt(result, prompts_already_sent=0, max_per_student=3)


def test_should_send_dynamic_prompt_respects_the_per_student_cap():
    result = compute_engagement(0.2, None)
    assert not should_send_dynamic_prompt(result, prompts_already_sent=3, max_per_student=3)


def test_comprehension_alert_guards_on_minimum_respondents():
    decision = evaluate_comprehension_alert(
        respondents=2, correct_count=0, min_respondents=5, threshold=0.5
    )
    assert decision.should_alert is False


def test_comprehension_alert_fires_below_threshold_with_enough_respondents():
    decision = evaluate_comprehension_alert(
        respondents=10, correct_count=3, min_respondents=5, threshold=0.5
    )
    assert decision.should_alert is True
    assert decision.correct_ratio == 0.3


def test_comprehension_alert_does_not_fire_above_threshold():
    decision = evaluate_comprehension_alert(
        respondents=10, correct_count=8, min_respondents=5, threshold=0.5
    )
    assert decision.should_alert is False
