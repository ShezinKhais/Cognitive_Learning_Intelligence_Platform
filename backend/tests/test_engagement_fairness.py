"""Cyber 1, Phase 6: engagement stays usable and fair when signals are missing.

Pure-logic tests of engagement.py v2 and engagement_baseline.py: weighted
renormalisation, the camera only corroborating, personal baselines, why a
signal is unavailable, and the rules for students with an accommodation.
"""

from __future__ import annotations

import pytest

from app.schemas.events import AttentionSignalPayload
from app.schemas.session import EngagementStatus
from app.services import engagement as engagement_module
from app.services.engagement import (
    ACCOMMODATED_UNSCORED,
    PROMPT_ACKNOWLEDGED,
    PROMPT_DISMISSED,
    PROMPT_EXPIRED,
    EngagementInputs,
    compute_engagement,
    should_send_dynamic_prompt,
)
from app.services.engagement_baseline import (
    GAZE_BASELINE_FLOOR,
    MAX_BASELINE_SAMPLES,
    MIN_BASELINE_SAMPLES,
    PersonalBaseline,
)


def camera(gaze: float | None = None, face: bool | None = None) -> AttentionSignalPayload:
    return AttentionSignalPayload(gaze_on_screen_ratio=gaze, face_present=face, window_seconds=5.0)


def baseline(gaze: list[float] = (), face: list[bool] = ()) -> PersonalBaseline:  # type: ignore[assignment]
    b = PersonalBaseline()
    for g in gaze:
        b.record(g, None)
    for f in face:
        b.record(None, f)
    return b


# -- the camera corroborates, it never accuses --------------------------------


def test_a_camera_alone_is_never_grounds_for_a_status() -> None:
    result = compute_engagement(EngagementInputs(attention=camera(0.0, False)))
    assert result.status == EngagementStatus.INSUFFICIENT_DATA
    assert result.score is None
    assert not should_send_dynamic_prompt(result)
    # What it did see is still reported, for explanations.
    assert result.signals_available == ["gaze", "face_presence"]


def test_a_student_answering_everything_is_not_pulled_down_by_the_camera() -> None:
    without = compute_engagement(EngagementInputs(questions_shown=4, questions_answered=4))
    looking_away = compute_engagement(
        EngagementInputs(questions_shown=4, questions_answered=4, attention=camera(0.0, False))
    )
    assert without.status == looking_away.status == EngagementStatus.ENGAGED
    assert looking_away.score == without.score == 1.0
    assert not should_send_dynamic_prompt(looking_away)


def test_the_camera_adds_to_low_participation_but_weighs_less_than_it() -> None:
    inputs = {"questions_shown": 4, "questions_answered": 1}  # attempt rate 0.25
    bare = compute_engagement(EngagementInputs(**inputs))
    away = compute_engagement(EngagementInputs(**inputs, attention=camera(0.0, False)))
    looking = compute_engagement(EngagementInputs(**inputs, attention=camera(1.0, True)))
    assert away.score < bare.score < looking.score
    # Two zero readings at half weight: 0.25 / (1 + 0.5 + 0.5).
    assert away.score == pytest.approx(0.25 / 2.0)
    assert looking.score == pytest.approx((0.25 + 1.0) / 2.0)


def test_one_camera_reading_cannot_turn_a_borderline_student_disengaged_alone() -> None:
    # Participation sits just above the at-risk line; a bad camera reading
    # lowers the score but a student is only DISENGAGED below that line.
    result = compute_engagement(
        EngagementInputs(questions_shown=10, questions_answered=4, attention=camera(0.0, False))
    )
    assert result.status == EngagementStatus.DISENGAGED  # 0.4 / 2.0 = 0.2
    # ...and the same student with a participation signal and no camera is
    # only at risk, which is what a camera-free class sees.
    no_camera = compute_engagement(EngagementInputs(questions_shown=10, questions_answered=4))
    assert no_camera.status == EngagementStatus.AT_RISK


def test_prompts_need_participation_among_the_signals() -> None:
    low = compute_engagement(
        EngagementInputs(
            questions_shown=4,
            questions_answered=0,
            prompt_responses=(PROMPT_EXPIRED,),
        )
    )
    assert should_send_dynamic_prompt(low)
    camera_only = compute_engagement(EngagementInputs(attention=camera(0.0, False)))
    assert not should_send_dynamic_prompt(camera_only)


# -- weighted renormalisation ---------------------------------------------------


def test_missing_signals_are_dropped_not_counted_as_zero() -> None:
    result = compute_engagement(
        EngagementInputs(
            questions_shown=2, questions_answered=2, prompt_responses=(PROMPT_DISMISSED,)
        )
    )
    assert result.signals_available == ["attempt_rate", "prompt_response"]
    assert result.score == pytest.approx((1.0 + 0.5) / 2)


def test_participation_weighs_more_than_the_camera() -> None:
    # Same two readings, 0 and 1: whichever is participation decides.
    participation_low = compute_engagement(
        EngagementInputs(questions_shown=2, questions_answered=0, attention=camera(1.0, None))
    )
    camera_low = compute_engagement(
        EngagementInputs(questions_shown=2, questions_answered=2, attention=camera(0.0, None))
    )
    assert participation_low.score == pytest.approx(0.5 / 1.5)
    assert camera_low.score == 1.0  # the camera cannot pull participation down


def test_confidence_is_the_weight_that_contributed_over_the_weight_that_could() -> None:
    assert compute_engagement(EngagementInputs()).confidence == 0.0
    one = compute_engagement(EngagementInputs(questions_shown=2, questions_answered=2))
    assert one.confidence == pytest.approx(1.0 / 4.0)
    everything = compute_engagement(
        EngagementInputs(
            questions_shown=2,
            questions_answered=2,
            response_times=(0.1,),
            prompt_responses=(PROMPT_ACKNOWLEDGED,),
            attention=camera(0.9, True),
        )
    )
    assert everything.confidence == pytest.approx(1.0)


# -- availability: every unscored signal says why --------------------------------


def test_every_signal_is_either_scored_or_has_a_reason() -> None:
    cases = [
        EngagementInputs(),
        EngagementInputs(questions_shown=1),
        EngagementInputs(questions_shown=3, questions_answered=2, response_times=(0.5,)),
        EngagementInputs(attention=camera(0.4, None)),
        EngagementInputs(accommodated=True, questions_shown=3, questions_answered=1),
    ]
    for case in cases:
        result = compute_engagement(case)
        names = set(engagement_module._SIGNAL_NAMES)
        assert set(result.signals_available) | set(result.unavailable) == names
        assert not set(result.signals_available) & set(result.unavailable)


def test_the_reasons_are_the_right_ones() -> None:
    result = compute_engagement(EngagementInputs(questions_shown=1, attention=camera(0.4, None)))
    assert result.unavailable == {
        "attempt_rate": engagement_module.REASON_TOO_FEW_QUESTIONS,
        "response_timing": engagement_module.REASON_NO_ANSWERS,
        "prompt_response": engagement_module.REASON_NO_PROMPTS,
        "face_presence": engagement_module.REASON_NO_CAMERA_SIGNAL,
    }


def test_no_camera_means_no_camera_signal_not_a_low_one() -> None:
    result = compute_engagement(EngagementInputs(questions_shown=2, questions_answered=2))
    assert result.unavailable["gaze"] == engagement_module.REASON_NO_CAMERA_SIGNAL
    assert result.unavailable["face_presence"] == engagement_module.REASON_NO_CAMERA_SIGNAL
    assert result.status == EngagementStatus.ENGAGED


def test_the_reasons_are_not_part_of_the_public_session_schema() -> None:
    from app.schemas.session import EngagementOut

    assert "unavailable" not in EngagementOut.model_fields


# -- personal baselines -------------------------------------------------------------


def test_a_student_who_usually_looks_at_notes_is_not_penalised_for_it() -> None:
    usual = baseline(gaze=[0.4, 0.4, 0.4, 0.4])
    inputs = {"questions_shown": 4, "questions_answered": 1}
    against_normal = compute_engagement(
        EngagementInputs(**inputs, attention=camera(0.4), baseline=usual)
    )
    no_baseline = compute_engagement(EngagementInputs(**inputs, attention=camera(0.4)))
    assert against_normal.score > no_baseline.score
    # 0.4 is 100% of this student's normal: (0.25 + 1.0 * 0.5) / 1.5
    assert against_normal.score == pytest.approx((0.25 + 0.5) / 1.5)


def test_a_drop_from_their_own_normal_still_counts() -> None:
    usual = baseline(gaze=[0.9, 0.9, 0.9, 0.9])
    inputs = {"questions_shown": 4, "questions_answered": 1}
    steady = compute_engagement(EngagementInputs(**inputs, attention=camera(0.9), baseline=usual))
    dropped = compute_engagement(EngagementInputs(**inputs, attention=camera(0.1), baseline=usual))
    assert dropped.score < steady.score


def test_a_baseline_is_not_trusted_before_it_has_enough_samples() -> None:
    thin = baseline(gaze=[0.1] * (MIN_BASELINE_SAMPLES - 1))
    assert thin.gaze_reference() is None
    inputs = {"questions_shown": 4, "questions_answered": 1}
    a = compute_engagement(EngagementInputs(**inputs, attention=camera(0.4), baseline=thin))
    b = compute_engagement(EngagementInputs(**inputs, attention=camera(0.4)))
    assert a.score == b.score


def test_a_baseline_is_never_lower_than_the_floor() -> None:
    nearly_never = baseline(gaze=[0.0, 0.0, 0.0, 0.0])
    assert nearly_never.gaze_reference() == GAZE_BASELINE_FLOOR
    result = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=1, attention=camera(0.125), baseline=nearly_never
        )
    )
    # 0.125 is half of the floor, not "normal".
    assert result.score == pytest.approx((0.25 + 0.5 * 0.5) / 1.5)


def test_a_camera_that_rarely_finds_the_face_is_set_aside_as_unreliable() -> None:
    poor = baseline(face=[False, False, False, True, False])
    assert not poor.face_reliable()
    result = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=1, attention=camera(None, False), baseline=poor
        )
    )
    assert "face_presence" not in result.signals_available
    assert result.unavailable["face_presence"] == engagement_module.REASON_CAMERA_UNRELIABLE


def test_a_reliable_camera_missing_the_face_counts() -> None:
    good = baseline(face=[True, True, True, True, False])
    result = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=1, attention=camera(None, False), baseline=good
        )
    )
    assert "face_presence" in result.signals_available


def test_a_slow_but_steady_answerer_is_not_penalised_for_being_slow() -> None:
    steady = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=4, response_times=(0.8, 0.8, 0.8, 0.8)
        )
    )
    assert steady.signals_available == ["attempt_rate", "response_timing"]
    timing = steady.score * 2 - 1.0  # attempt_rate is 1.0
    assert timing == pytest.approx(1.0)


def test_slowing_down_from_their_own_pace_does_cost() -> None:
    fast_then_slow = compute_engagement(
        EngagementInputs(
            questions_shown=5, questions_answered=5, response_times=(0.1, 0.1, 0.1, 0.9, 0.9)
        )
    )
    steady = compute_engagement(
        EngagementInputs(
            questions_shown=5, questions_answered=5, response_times=(0.5, 0.5, 0.5, 0.5, 0.5)
        )
    )
    assert fast_then_slow.score < steady.score


def test_few_answers_use_the_plain_timing_rule() -> None:
    result = compute_engagement(EngagementInputs(response_times=(0.4, 0.6)))
    assert result.score == pytest.approx(0.75)


def test_baseline_history_is_bounded_and_can_be_purged() -> None:
    b = PersonalBaseline()
    for _ in range(MAX_BASELINE_SAMPLES * 2):
        b.record(0.5, True)
    assert len(b.gaze) == len(b.face) == MAX_BASELINE_SAMPLES
    b.purge_visual()
    assert (b.gaze, b.face) == ([], [])
    assert b.gaze_reference() is None and b.face_reliable()


def test_recording_a_missing_value_adds_nothing() -> None:
    b = PersonalBaseline()
    b.record(None, None)
    assert (b.gaze, b.face) == ([], [])


# -- accessibility rules --------------------------------------------------------------


def accommodated(**kwargs: object) -> EngagementInputs:
    return EngagementInputs(accommodated=True, **kwargs)  # type: ignore[arg-type]


def test_an_accommodated_student_is_not_scored_on_how_they_interact() -> None:
    result = compute_engagement(
        accommodated(
            questions_shown=4,
            questions_answered=4,
            response_times=(0.99, 0.99, 0.99),
            attention=camera(0.0, False),
        )
    )
    assert result.signals_available == ["attempt_rate"]
    assert result.score == 1.0
    for name in ACCOMMODATED_UNSCORED:
        assert result.unavailable[name] == engagement_module.REASON_ACCOMMODATION


def test_an_expired_prompt_is_not_held_against_an_accommodated_student() -> None:
    result = compute_engagement(
        accommodated(
            questions_shown=4,
            questions_answered=3,
            prompt_responses=(PROMPT_EXPIRED, PROMPT_EXPIRED),
        )
    )
    assert "prompt_response" not in result.signals_available
    assert result.unavailable["prompt_response"] == engagement_module.REASON_NO_PROMPTS


def test_an_accommodated_student_who_answers_a_prompt_is_still_credited() -> None:
    result = compute_engagement(
        accommodated(
            questions_shown=4,
            questions_answered=3,
            prompt_responses=(PROMPT_EXPIRED, PROMPT_ACKNOWLEDGED),
        )
    )
    assert "prompt_response" in result.signals_available
    assert result.score == pytest.approx((0.75 + 1.0) / 2)


def test_an_accommodated_student_is_never_disengaged_or_prompted() -> None:
    result = compute_engagement(
        accommodated(
            questions_shown=6,
            questions_answered=0,
            prompt_responses=(0.1,),
        )
    )
    assert result.status == EngagementStatus.AT_RISK
    assert result.accommodated
    assert not should_send_dynamic_prompt(result)


def test_an_unaccommodated_student_in_the_same_position_is_prompted() -> None:
    result = compute_engagement(
        EngagementInputs(questions_shown=6, questions_answered=0, prompt_responses=(0.1,))
    )
    assert result.status == EngagementStatus.DISENGAGED
    assert should_send_dynamic_prompt(result)


def test_accommodated_confidence_is_judged_against_what_could_apply() -> None:
    result = compute_engagement(accommodated(questions_shown=4, questions_answered=4))
    # attempt_rate (1.0) of attempt_rate + prompt_response (2.0)
    assert result.confidence == pytest.approx(0.5)
    assert (
        result.confidence
        > compute_engagement(EngagementInputs(questions_shown=4, questions_answered=4)).confidence
    )


def test_the_accommodation_flag_never_carries_the_need_itself() -> None:
    # The computation has a boolean and nothing else about the student.
    fields = {f for f in engagement_module.EngagementComputation.__dataclass_fields__}
    assert "accommodated" in fields
    assert not {"need", "accessibility_need", "accommodation", "reason_text"} & fields
    assert {f for f in engagement_module.EngagementInputs.__dataclass_fields__}.isdisjoint(
        {"need", "accessibility_need", "accommodation"}
    )


@pytest.mark.parametrize("answered", range(0, 7))
def test_fairness_properties_hold_across_participation_levels(answered: int) -> None:
    """For every attempt rate: the camera never lowers an engaged student, and
    an accommodated student never ends up disengaged or prompted."""
    for cam in (None, camera(0.0, False), camera(1.0, True), camera(0.3, None)):
        plain = compute_engagement(EngagementInputs(questions_shown=6, questions_answered=answered))
        with_cam = compute_engagement(
            EngagementInputs(questions_shown=6, questions_answered=answered, attention=cam)
        )
        if plain.status == EngagementStatus.ENGAGED:
            assert with_cam.status == EngagementStatus.ENGAGED
        acc = compute_engagement(
            accommodated(questions_shown=6, questions_answered=answered, attention=cam)
        )
        assert acc.status != EngagementStatus.DISENGAGED
        assert not should_send_dynamic_prompt(acc)


# -- cases found by mutation testing ----------------------------------------------------


def test_a_camera_only_computation_is_never_prompted_even_if_it_were_low() -> None:
    forged = engagement_module.EngagementComputation(
        score=0.1,
        status=EngagementStatus.DISENGAGED,
        confidence=0.5,
        signals_available=["gaze", "face_presence"],
    )
    assert not should_send_dynamic_prompt(forged)


def test_gaze_above_the_students_normal_is_capped_at_full() -> None:
    low_normal = baseline(gaze=[0.25] * 4)
    result = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=1, attention=camera(0.9), baseline=low_normal
        )
    )
    assert result.score == pytest.approx((0.25 + 0.5) / 1.5)
    assert 0.0 <= result.score <= 1.0


def test_answering_faster_than_usual_costs_nothing() -> None:
    result = compute_engagement(
        EngagementInputs(
            questions_shown=5, questions_answered=5, response_times=(0.9, 0.9, 0.9, 0.1, 0.1)
        )
    )
    assert result.score == pytest.approx(1.0)


def test_two_readings_are_too_few_to_call_a_camera_unreliable() -> None:
    thin = baseline(face=[False, False])
    assert thin.face_rate() is None and thin.face_reliable()
    result = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=1, attention=camera(None, False), baseline=thin
        )
    )
    assert "face_presence" in result.signals_available
