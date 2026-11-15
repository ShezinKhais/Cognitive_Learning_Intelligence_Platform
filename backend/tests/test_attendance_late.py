"""Late marking in attendance, measured from the later of the timetabled and
actual start. Owner: General CS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services import attendance
from app.services.attendance import _is_late, _late_after, _Seen

START = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


def _seen(minutes: int) -> _Seen:
    seen = _Seen()
    seen.add("teams", START + timedelta(minutes=minutes), START + timedelta(minutes=60))
    return seen


def _settings(minutes: int):  # noqa: ANN202
    return SimpleNamespace(attendance_late_minutes=minutes)


def test_joining_more_than_twenty_minutes_in_is_late(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(attendance, "get_settings", lambda: _settings(20))
    after = _late_after(SimpleNamespace(start_time=START, started_at=None))
    assert not _is_late(_seen(19), after)
    assert not _is_late(_seen(20), after)
    assert _is_late(_seen(21), after)
    assert not _is_late(None, after)


def test_a_class_that_started_late_counts_from_its_actual_start(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(attendance, "get_settings", lambda: _settings(20))
    session = SimpleNamespace(start_time=START, started_at=START + timedelta(minutes=15))
    assert not _is_late(_seen(30), _late_after(session))
    assert _is_late(_seen(36), _late_after(session))


def test_a_class_started_early_counts_from_its_timetabled_start(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(attendance, "get_settings", lambda: _settings(20))
    session = SimpleNamespace(start_time=START, started_at=START - timedelta(minutes=10))
    assert not _is_late(_seen(15), _late_after(session))


def test_zero_marks_nobody_late(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(attendance, "get_settings", lambda: _settings(0))
    assert _late_after(SimpleNamespace(start_time=START, started_at=None)) is None
    assert not _is_late(_seen(90), None)
