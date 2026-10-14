"""Cyber 1, Phase 6: fair engagement in a running class.

The accommodation rule, the personal baseline and the consent-driven purge,
exercised through the classroom rather than the scoring functions.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.realtime.accommodations import Accommodations, has_accommodation
from app.realtime.classroom import Classroom
from app.realtime.consent import ConsentRegistry
from app.schemas.events import AttentionSignalPayload, ServerEventType
from app.schemas.identity import ConsentType, Role

from .classroom_support import answer_to, deliver_next, join_as, make_room, make_row

pytestmark = pytest.mark.usefixtures("fake_session_repository")


@pytest.fixture(autouse=True)
def _no_signal_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests send several readings a fraction of a second apart. The
    server drops a student's signal that follows the last within
    MIN_SIGNAL_INTERVAL (attention_windows.py); that rule has its own tests."""
    from datetime import timedelta

    from app.realtime import attention_windows

    monkeypatch.setattr(attention_windows, "MIN_SIGNAL_INTERVAL", timedelta(0))


ALL = {
    ConsentType.TERMS,
    ConsentType.ENGAGEMENT_MONITORING,
    ConsentType.CAMERA,
    ConsentType.MICROPHONE,
}


async def _room(*, accommodated: bool = False):  # noqa: ANN202
    room, events = make_room(window=0.05, missed=0, consents=ConsentRegistry())
    row = make_row()
    room.activate(row.session_id)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    room.admit_consents(student, ALL, room.consents.version(student))
    room.accommodations.set(student, accommodated)
    return room, row, socket, student


async def _close(room: Classroom, row: SimpleNamespace, answer=None) -> None:  # noqa: ANN001
    question = await deliver_next(room, row)
    if answer is not None:
        assert (
            await room.submit(row.session_id, answer, Role.STUDENT, answer_to(question.question_id))
        ).accepted
    await asyncio.sleep(0.15)


def _gaze(ratio: float, face: bool | None = None) -> AttentionSignalPayload:
    return AttentionSignalPayload(gaze_on_screen_ratio=ratio, face_present=face, window_seconds=5)


async def test_an_accommodated_student_who_misses_questions_is_never_nudged_or_disengaged() -> None:
    room, row, socket, student = await _room(accommodated=True)
    for _ in range(4):
        await _close(room, row)
    [scored] = room.engagement(row.session_id)
    assert scored.engagement.status.value == "at_risk"
    assert scored.engagement.accommodated
    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_the_same_student_without_an_accommodation_gets_the_ordinary_rules() -> None:
    room, row, socket, student = await _room(accommodated=False)
    assert await room.prompt_student(row.session_id, student, "Still with us?")
    await asyncio.sleep(0.01)
    await room.shutdown()
    # (the ordinary nudge path is covered in test_classroom_attention.py; here
    # the point is that nothing about the accommodated case leaks into it)
    assert student not in room.accommodations


async def test_an_accommodated_students_camera_is_not_scored_even_when_sent() -> None:
    room, row, _, student = await _room(accommodated=True)
    assert await room.record_attention(row.session_id, student, _gaze(0.0, False))
    await _close(room, row, student)
    await _close(room, row, student)
    [scored] = room.engagement(row.session_id)
    assert "gaze" not in scored.engagement.signals_available
    assert "face_presence" not in scored.engagement.signals_available
    assert scored.engagement.status.value == "engaged"
    await room.shutdown()


async def test_the_class_learns_a_students_normal_from_their_own_readings() -> None:
    room, row, _, student = await _room()
    for _ in range(3):
        assert await room.record_attention(row.session_id, student, _gaze(0.4, True))
        await _close(room, row)
    live = room._live[row.session_id]
    assert len(live.attention._students[student].baseline.gaze) == 3
    await room.shutdown()


async def test_one_reading_is_not_counted_twice_across_questions() -> None:
    room, row, _, student = await _room()
    assert await room.record_attention(row.session_id, student, _gaze(0.4, True))
    for _ in range(3):
        await _close(room, row)
    live = room._live[row.session_id]
    assert len(live.attention._students[student].baseline.gaze) == 1
    await room.shutdown()


async def test_withdrawing_the_camera_forgets_what_the_camera_taught() -> None:
    room, row, _, student = await _room()
    for _ in range(3):
        assert await room.record_attention(row.session_id, student, _gaze(0.4, True))
        await _close(room, row)
    await room.withdraw_consent(student, ConsentType.CAMERA)
    held = room._live[row.session_id].attention._students[student].baseline
    assert (held.gaze, held.face) == ([], [])
    await room.shutdown()


async def test_withdrawing_the_microphone_leaves_the_camera_baseline_alone() -> None:
    room, row, _, student = await _room()
    for _ in range(3):
        assert await room.record_attention(row.session_id, student, _gaze(0.4, True))
        await _close(room, row)
    await room.withdraw_consent(student, ConsentType.MICROPHONE)
    held = room._live[row.session_id].attention._students[student].baseline
    assert len(held.gaze) == 3
    await room.shutdown()


async def test_withdrawing_monitoring_drops_the_baseline_with_everything_else() -> None:
    room, row, _, student = await _room()
    for _ in range(3):
        assert await room.record_attention(row.session_id, student, _gaze(0.4, True))
        await _close(room, row)
    await room.withdraw_consent(student, ConsentType.ENGAGEMENT_MONITORING)
    held = room._live[row.session_id].attention._students[student].baseline
    assert (held.gaze, held.face) == ([], [])
    await room.shutdown()


# -- the accommodation lookup ------------------------------------------------------


class _Db:
    """Stands in for the session the lookup reads through."""


def _student_row(need):  # noqa: ANN001, ANN202
    return SimpleNamespace(accessibility_need=need)


@pytest.mark.parametrize(
    ("need", "expected"),
    [(None, False), ("", False), ("   ", False), ("screen reader", True), ("x", True)],
)
async def test_only_the_presence_of_a_need_matters(
    monkeypatch: pytest.MonkeyPatch, need: str | None, expected: bool
) -> None:
    from app.realtime import accommodations as module

    class Repo:
        def __init__(self, db: object) -> None: ...

        async def get_by_user_id(self, user_id):  # noqa: ANN001, ANN201
            return _student_row(need)

    monkeypatch.setattr(module, "StudentRepository", Repo)
    assert await has_accommodation(_Db(), uuid4()) is expected  # type: ignore[arg-type]


async def test_a_user_with_no_student_record_has_no_accommodation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.realtime import accommodations as module

    class Repo:
        def __init__(self, db: object) -> None: ...

        async def get_by_user_id(self, user_id):  # noqa: ANN001, ANN201
            return None

    monkeypatch.setattr(module, "StudentRepository", Repo)
    assert await has_accommodation(_Db(), uuid4()) is False  # type: ignore[arg-type]


async def test_a_record_that_cannot_be_read_counts_as_accommodated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.realtime import accommodations as module

    class Repo:
        def __init__(self, db: object) -> None: ...

        async def get_by_user_id(self, user_id):  # noqa: ANN001, ANN201
            raise RuntimeError("database down: screen reader dyslexia")

    monkeypatch.setattr(module, "StudentRepository", Repo)
    with caplog.at_level(logging.DEBUG):
        assert await has_accommodation(_Db(), uuid4()) is True  # type: ignore[arg-type]
    # The error text, which could carry a record's content, is not logged.
    assert "dyslexia" not in caplog.text


async def test_the_text_of_a_need_is_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.realtime import accommodations as module

    secret = "profound-hearing-loss-4471"

    class Repo:
        def __init__(self, db: object) -> None: ...

        async def get_by_user_id(self, user_id):  # noqa: ANN001, ANN201
            return _student_row(secret)

    monkeypatch.setattr(module, "StudentRepository", Repo)
    with caplog.at_level(logging.DEBUG):
        assert await has_accommodation(_Db(), uuid4()) is True  # type: ignore[arg-type]
    assert secret not in caplog.text


def test_accommodations_registry_is_a_set_of_ids_and_nothing_else() -> None:
    registry = Accommodations()
    a, b = uuid4(), uuid4()
    registry.set(a, True)
    registry.set(b, False)
    assert a in registry and b not in registry
    assert registry.members() == frozenset({a})
    registry.set(a, False)
    assert registry.members() == frozenset()


async def test_the_lecturers_view_does_not_reveal_who_is_accommodated() -> None:
    from datetime import UTC, datetime

    from app.schemas.session import EngagementOut

    room, row, _, student = await _room(accommodated=True)
    await _close(room, row)
    [scored] = room.engagement(row.session_id)
    out = EngagementOut(
        student_id=uuid4(),
        session_id=row.session_id,
        score=scored.engagement.score,
        status=scored.engagement.status,
        confidence=scored.engagement.confidence,
        signals_available=scored.engagement.signals_available,
        computed_at=datetime.now(UTC),
    )
    dumped = out.model_dump_json()
    for word in ("accommodat", "accessib", "unavailable", "reason"):
        assert word not in dumped
    await room.shutdown()


async def test_the_scorer_reads_a_student_against_their_own_baseline() -> None:
    from datetime import UTC, datetime, timedelta

    from app.realtime.attention import Attention

    attention = Attention(uuid4())
    student = uuid4()
    now = datetime.now(UTC)
    for _ in range(3):
        attention.observe(student, _gaze(0.4), now)
        attention.score({student}, set(), {}, now)
        now = now + timedelta(seconds=3)
    # attempt rate 0, gaze 0.4 which is 100% of their own normal
    [scored] = attention.scores()
    assert scored.engagement.score == pytest.approx(0.5 / 1.5)


async def test_an_error_while_checking_never_logs_its_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.realtime import accommodations as module

    class Repo:
        def __init__(self, db: object) -> None: ...

        async def get_by_user_id(self, user_id):  # noqa: ANN001, ANN201
            raise RuntimeError("row accessibility_need=wheelchair-user")

    monkeypatch.setattr(module, "StudentRepository", Repo)
    with caplog.at_level(logging.DEBUG):
        await has_accommodation(_Db(), uuid4())  # type: ignore[arg-type]
    assert "wheelchair" not in caplog.text
    assert "wheelchair" not in " ".join(str(r.exc_info) for r in caplog.records)
