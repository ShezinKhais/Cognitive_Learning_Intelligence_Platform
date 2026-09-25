"""Pure-logic tests for Phase 3 camera-free engagement scoring, dynamic
prompt gating and class comprehension alerts.

Owner: Cyber 1, Phase 3. No database or app fixture needed -- these are
plain functions. The live paths that call them are in test_classroom_attention.py.
"""

from app.schemas.events import AttentionSignalPayload
from app.schemas.session import EngagementStatus
from app.services.engagement import (
    PROMPT_ACKNOWLEDGED,
    PROMPT_EXPIRED,
    EngagementInputs,
    compute_engagement,
    evaluate_comprehension_alert,
    should_send_dynamic_prompt,
)


def test_no_evidence_is_insufficient_data():
    result = compute_engagement(EngagementInputs())
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert result.score is None
    assert result.signals_available == []


def test_a_late_joiner_shown_one_question_has_no_attempt_rate_yet():
    result = compute_engagement(EngagementInputs(questions_shown=1, questions_answered=0))
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert not should_send_dynamic_prompt(result)


def test_attempt_rate_counts_only_questions_the_student_was_shown():
    result = compute_engagement(EngagementInputs(questions_shown=2, questions_answered=2))
    assert result.signals_available == ["attempt_rate"]
    assert result.score == 1.0
    assert result.status == EngagementStatus.ENGAGED


def test_a_low_attempt_rate_alone_is_at_risk_and_never_prompts():
    result = compute_engagement(EngagementInputs(questions_shown=4, questions_answered=0))
    assert result.status == EngagementStatus.AT_RISK
    assert not should_send_dynamic_prompt(result)


def test_a_second_low_signal_makes_it_disengaged_and_prompts():
    result = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=0, prompt_responses=(PROMPT_EXPIRED,)
        )
    )
    assert result.signals_available == ["attempt_rate", "prompt_response"]
    assert result.status == EngagementStatus.DISENGAGED
    assert should_send_dynamic_prompt(result)


def test_answering_early_scores_higher_than_answering_late():
    early = compute_engagement(
        EngagementInputs(questions_shown=2, questions_answered=2, response_times=(0.1, 0.1))
    )
    late = compute_engagement(
        EngagementInputs(questions_shown=2, questions_answered=2, response_times=(0.9, 0.9))
    )
    assert early.score > late.score
    # Answering at all, however late, is still engagement.
    assert late.status == EngagementStatus.ENGAGED


def test_acknowledging_prompts_lifts_the_score():
    ignored = compute_engagement(
        EngagementInputs(questions_shown=4, questions_answered=1, prompt_responses=(0.0,))
    )
    answered = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=1, prompt_responses=(PROMPT_ACKNOWLEDGED,)
        )
    )
    assert answered.score > ignored.score


def test_gaze_is_optional_and_missing_signals_are_renormalised():
    attention = AttentionSignalPayload(gaze_on_screen_ratio=0.9, window_seconds=5.0)
    result = compute_engagement(
        EngagementInputs(questions_shown=2, questions_answered=2, attention=attention)
    )
    assert result.signals_available == ["attempt_rate", "gaze"]
    assert result.score == 0.95
    assert result.confidence == 2 / 5


def test_speaking_is_never_scored():
    quiet = AttentionSignalPayload(gaze_on_screen_ratio=0.65, speaking=False, window_seconds=5.0)
    loud = AttentionSignalPayload(gaze_on_screen_ratio=0.65, speaking=True, window_seconds=5.0)
    inputs = {"questions_shown": 2, "questions_answered": 1}
    a = compute_engagement(EngagementInputs(**inputs, attention=quiet))
    b = compute_engagement(EngagementInputs(**inputs, attention=loud))
    assert a.score == b.score
    assert "speaking" not in a.signals_available


def test_insufficient_data_never_prompts():
    assert not should_send_dynamic_prompt(compute_engagement(EngagementInputs()))


def test_comprehension_alert_needs_the_minimum_respondents():
    decision = evaluate_comprehension_alert(
        ["struggling", "struggling"], min_respondents=5, threshold=0.5
    )
    assert decision.should_alert is False
    assert decision.correct_ratio is None


def test_comprehension_alert_fires_at_half_partial_or_struggling():
    labels = ["mastered"] * 5 + ["partial"] * 3 + ["struggling"] * 2
    decision = evaluate_comprehension_alert(labels, min_respondents=5, threshold=0.5)
    assert decision.should_alert is True
    assert decision.correct_ratio == 0.5
    assert decision.struggling_ratio == 0.5


def test_comprehension_alert_does_not_fire_when_most_mastered_it():
    labels = ["mastered"] * 8 + ["partial"] * 2
    decision = evaluate_comprehension_alert(labels, min_respondents=5, threshold=0.5)
    assert decision.should_alert is False


def test_unclassified_answers_are_not_valid_respondents():
    labels = ["struggling"] * 4 + ["pending", ""]
    decision = evaluate_comprehension_alert(labels, min_respondents=5, threshold=0.5)
    assert decision.respondents == 4
    assert decision.should_alert is False


def test_comprehension_alert_zero_respondents_does_not_divide_by_zero():
    decision = evaluate_comprehension_alert([], min_respondents=0, threshold=0.5)
    assert decision.should_alert is False
    assert decision.correct_ratio is None
