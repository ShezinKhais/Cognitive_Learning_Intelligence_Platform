"""Pure-logic tests for Phase 3 camera-free engagement scoring, dynamic
prompt gating and class comprehension alerts.

Owner: Cyber 1, Phase 3. No database or app fixture needed -- these are
plain functions.
"""

from app.schemas.events import AttentionSignalPayload
from app.schemas.session import EngagementStatus
from app.services.engagement import (
    compute_engagement,
    evaluate_comprehension_alert,
    should_send_dynamic_prompt,
)


def test_compute_engagement_with_no_signals_is_insufficient_data():
    result = compute_engagement(None, None)
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert result.score is None
    assert result.signals_available == []


def test_compute_engagement_attempt_rate_alone_is_just_enough_confidence():
    result = compute_engagement(0.8, None)
    assert result.status == EngagementStatus.ENGAGED
    assert result.signals_available == ["attempt_rate"]
    assert result.confidence == 1 / 3


def test_compute_engagement_low_attempt_rate_alone_is_at_risk_not_disengaged():
    """A single signal (attempt_rate alone) is not enough evidence for the
    module's strongest judgement call -- see module docstring. A second,
    corroborating signal is required before DISENGAGED is returned."""
    result = compute_engagement(0.1, None)
    assert result.status == EngagementStatus.AT_RISK


def test_compute_engagement_low_attempt_rate_with_corroborating_signal_is_disengaged():
    attention = AttentionSignalPayload(gaze_on_screen_ratio=0.1, window_seconds=5.0)
    result = compute_engagement(0.1, attention)
    assert result.signals_available == ["attempt_rate", "gaze"]
    assert result.status == EngagementStatus.DISENGAGED


def test_compute_engagement_renormalises_missing_signals():
    """Only gaze reported (no face presence) still yields a full-confidence
    read once attempt_rate is added -- the missing component is dropped
    from the average rather than counted as zero."""
    attention = AttentionSignalPayload(gaze_on_screen_ratio=0.9, window_seconds=5.0)
    result = compute_engagement(0.9, attention)
    assert result.signals_available == ["attempt_rate", "gaze"]
    assert result.score == 0.9
    assert result.status == EngagementStatus.ENGAGED


def test_compute_engagement_speaking_false_is_excluded_not_penalised():
    """A quietly engaged student (not speaking, but attentive) must not be
    dragged down to AT_RISK by treating speaking=False as a 0.3 penalty --
    it's excluded from the average the same way a missing signal is."""
    attention = AttentionSignalPayload(
        gaze_on_screen_ratio=0.65, speaking=False, window_seconds=5.0
    )
    result = compute_engagement(0.65, attention)
    assert result.signals_available == ["attempt_rate", "gaze"]
    assert result.score == 0.65
    assert result.status == EngagementStatus.ENGAGED


def test_compute_engagement_speaking_true_does_not_affect_score():
    """Voice activity is not evidence of engagement, so speaking is recorded
    on the payload but never scored, in either direction."""
    attention = AttentionSignalPayload(gaze_on_screen_ratio=0.65, speaking=True, window_seconds=5.0)
    result = compute_engagement(0.65, attention)
    assert result.signals_available == ["attempt_rate", "gaze"]
    assert result.score == 0.65


def test_compute_engagement_zero_signals_never_reports_disengaged():
    """No evidence at all must render as insufficient data, never as a
    confident disengagement call -- see EngagementOut's own docstring."""
    result = compute_engagement(None, None)
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert result.status != EngagementStatus.DISENGAGED


def test_should_send_dynamic_prompt_never_fires_on_insufficient_data():
    result = compute_engagement(None, None)
    assert not should_send_dynamic_prompt(result)


def test_should_send_dynamic_prompt_fires_when_at_risk():
    result = compute_engagement(0.2, None)
    assert should_send_dynamic_prompt(result)


def test_should_send_dynamic_prompt_fires_when_disengaged():
    attention = AttentionSignalPayload(gaze_on_screen_ratio=0.1, window_seconds=5.0)
    result = compute_engagement(0.1, attention)
    assert result.status == EngagementStatus.DISENGAGED
    assert should_send_dynamic_prompt(result)


def test_comprehension_alert_guards_on_minimum_respondents():
    decision = evaluate_comprehension_alert(
        respondents=2, correct_count=0, min_respondents=5, threshold=0.5
    )
    assert decision.should_alert is False
    assert decision.correct_ratio is None


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


def test_comprehension_alert_zero_respondents_does_not_divide_by_zero():
    """Guards on respondents == 0 explicitly, independent of min_respondents
    -- a min_respondents of 0 must not let the division through."""
    decision = evaluate_comprehension_alert(
        respondents=0, correct_count=0, min_respondents=0, threshold=0.5
    )
    assert decision.should_alert is False
    assert decision.correct_ratio is None
