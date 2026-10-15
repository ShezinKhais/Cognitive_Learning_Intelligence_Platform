"""Cyber 1, Phase 6: what staff see cannot reveal an accommodation.

Reviewers (Aliyeh, Luna) pointed out that signals_available and confidence, shown
per student, would let a lecturer tell who has an accommodation: answer speed,
gaze and face presence are never scored for them. These tests hold the fix: one
view for everyone, computed from participation evidence only and capped at what
every student can have.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.realtime.classroom import classroom
from app.schemas.events import AttentionSignalPayload
from app.schemas.identity import ConsentType, Role
from app.services.engagement import (
    PROMPT_ACKNOWLEDGED,
    PROMPT_EXPIRED,
    EngagementInputs,
    compute_engagement,
)
from app.services.engagement_baseline import PersonalBaseline
from app.services.engagement_view import (
    COMMON_CEILING,
    PARTICIPATION,
    staff_confidence,
    staff_signals,
)

from .session_support import add_course, create_session, enrol, sign_in_as


def _every_input(accommodated: bool):  # noqa: ANN202
    cameras = [
        None,
        AttentionSignalPayload(gaze_on_screen_ratio=0.2, window_seconds=5),
        AttentionSignalPayload(face_present=False, window_seconds=5),
        AttentionSignalPayload(gaze_on_screen_ratio=0.9, face_present=True, window_seconds=5),
    ]
    baseline = PersonalBaseline()
    for _ in range(3):
        baseline.record(0.5, True)
    for shown, answered, times, prompts, camera, base in itertools.product(
        (0, 1, 2, 5),
        (0, 1, 2, 5),
        ((), (0.3,), (0.3, 0.4, 0.5)),
        ((), (PROMPT_ACKNOWLEDGED,), (PROMPT_EXPIRED,), (PROMPT_ACKNOWLEDGED, PROMPT_EXPIRED)),
        cameras,
        (None, baseline),
    ):
        if answered > shown:
            continue
        yield compute_engagement(
            EngagementInputs(
                questions_shown=shown,
                questions_answered=answered,
                response_times=times,
                prompt_responses=prompts,
                attention=camera,
                baseline=base,
                accommodated=accommodated,
            )
        )


def _views(accommodated: bool) -> set[tuple[tuple[str, ...], float]]:
    return {
        (tuple(staff_signals(c.signals_available)), staff_confidence(c.signals_available))
        for c in _every_input(accommodated)
    }


def test_every_view_an_accommodated_student_can_have_is_one_anyone_can_have() -> None:
    accommodated, everyone_else = _views(True), _views(False)
    assert accommodated <= everyone_else
    # ...and the other way: nothing the rest can show is out of reach of them,
    # so seeing a view says nothing about which kind of student it is.
    assert everyone_else <= accommodated


def test_the_view_is_a_function_of_whether_there_was_participation() -> None:
    for names, expected in (
        ([], (0.0, [])),
        (["attempt_rate"], (1.0, [PARTICIPATION])),
        (["prompt_response"], (1.0, [PARTICIPATION])),
        (["attempt_rate", "prompt_response"], (1.0, [PARTICIPATION])),
        (["attempt_rate", "response_timing", "prompt_response"], (1.0, [PARTICIPATION])),
        (["gaze", "face_presence"], (0.0, [])),
        (["attempt_rate", "gaze", "face_presence"], (1.0, [PARTICIPATION])),
    ):
        assert (staff_confidence(names), staff_signals(names)) == expected, names
    assert COMMON_CEILING == 1


def test_camera_signals_are_never_named_to_staff() -> None:
    for computation in _every_input(False):
        shown = staff_signals(computation.signals_available)
        assert set(shown) <= {PARTICIPATION}


def test_the_internal_computation_still_knows_the_detail() -> None:
    plain = compute_engagement(
        EngagementInputs(questions_shown=4, questions_answered=4, response_times=(0.2,))
    )
    assert plain.signals_available == ["attempt_rate", "response_timing"]
    accommodated = compute_engagement(
        EngagementInputs(
            questions_shown=4, questions_answered=4, response_times=(0.2,), accommodated=True
        )
    )
    assert accommodated.signals_available == ["attempt_rate"]
    assert accommodated.unavailable["response_timing"] == "accommodation"


@pytest.mark.usefixtures("fake_session_repository")
async def test_the_staff_route_reports_an_accommodated_student_like_any_other(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    session_id = session["id"]
    from uuid import UUID

    live = classroom.activate(UUID(session_id), paused=True)
    classroom.admit_consents(
        STUDENT_ID,
        {ConsentType.TERMS, ConsentType.ENGAGEMENT_MONITORING, ConsentType.CAMERA},
        read_at=0,
    )
    seen = []
    try:
        for accommodated in (False, True):
            classroom.accommodations.set(STUDENT_ID, accommodated)
            live.attention.observe(
                STUDENT_ID,
                AttentionSignalPayload(
                    gaze_on_screen_ratio=0.1, face_present=False, window_seconds=5
                ),
                datetime.now(UTC),
            )
            for _ in range(3):
                live.attention.score(
                    {STUDENT_ID},
                    {STUDENT_ID},
                    {STUDENT_ID: 0.4},
                    datetime.now(UTC),
                    classroom.accommodations.members(),
                )
            [scored] = client.get(f"/api/v1/sessions/{session_id}/engagement").json()
            seen.append(scored)
    finally:
        classroom.accommodations.set(STUDENT_ID, False)
        classroom._live.pop(UUID(session_id), None)

    plain, accommodated = seen
    assert plain["signals_available"] == accommodated["signals_available"] == [PARTICIPATION]
    assert plain["confidence"] == accommodated["confidence"] == 1.0
    assert "accommodat" not in str(accommodated).lower()
