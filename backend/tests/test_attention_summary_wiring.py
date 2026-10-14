"""The startup AttentionRecorder: finished minutes reach BBIS's
attention_signal_summary, against a real database.

Owner: General CS, Phase 6 (#59).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.realtime.recorders import AttentionWindow
from app.repositories.attention_signal_repository import list_for_session
from app.schemas.events import AttentionSignalPayload
from app.services.live_wiring import _AttentionSummaries

from .test_attention_signal_repository import classroom, database  # noqa: F401

MINUTE = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


def _window(session_id, user_id, start=MINUTE, **fields):  # noqa: ANN001, ANN003, ANN202
    fields.setdefault("window_seconds", 5.0)
    return AttentionWindow(
        session_id=session_id,
        user_id=user_id,
        window_start=start,
        signals=(AttentionSignalPayload(**fields), AttentionSignalPayload(**fields)),
    )


@pytest.fixture
def learner(classroom):  # noqa: ANN001, ANN201, F811
    """The student's user id: the classroom knows students by user, the table
    by student_id."""
    return classroom.users[1]


async def test_a_minute_is_stored_under_the_students_id(database, classroom, learner) -> None:  # noqa: ANN001, F811
    await _AttentionSummaries().record_windows(
        [_window(classroom.session, learner, gaze_on_screen_ratio=0.5, speaking=True)]
    )

    async with database() as db:
        [row] = await list_for_session(db, classroom.session)
    assert row.student_id == classroom.student
    assert (row.window_start, row.sample_count, row.window_seconds) == (MINUTE, 2, 10.0)
    assert (row.gaze_on_screen_ratio, row.speaking_ratio) == (0.5, 1.0)
    assert row.face_present_ratio is None


async def test_a_minute_already_stored_costs_only_that_minute(database, classroom, learner) -> None:  # noqa: ANN001, F811
    summaries = _AttentionSummaries()
    await summaries.record_windows([_window(classroom.session, learner, speaking=True)])

    await summaries.record_windows(
        [
            _window(classroom.session, learner, speaking=False),
            _window(classroom.session, learner, MINUTE + timedelta(minutes=1), speaking=False),
        ]
    )

    async with database() as db:
        rows = await list_for_session(db, classroom.session)
    assert [(r.window_start, r.speaking_ratio) for r in rows] == [
        (MINUTE, 1.0),
        (MINUTE + timedelta(minutes=1), 0.0),
    ]


async def test_a_user_who_is_not_a_student_is_skipped(
    database,  # noqa: ANN001, F811
    classroom,  # noqa: ANN001, F811
    learner,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="clip.classroom"):
        await _AttentionSummaries().record_windows(
            [_window(classroom.session, uuid4()), _window(classroom.session, learner)]
        )

    # Skipped, not tried and mistaken for a minute already stored.
    assert "already stored" not in caplog.text

    async with database() as db:
        rows = await list_for_session(db, classroom.session)
    assert [r.student_id for r in rows] == [classroom.student]
