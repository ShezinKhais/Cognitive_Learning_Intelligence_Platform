"""The purge of upload files past the retention period, and the scheduled run.

Owner: General CS, Phase 7 (#65).

No database is needed. The purge works on a directory under `tmp_path` with
file times set by hand. Filesystem calls live in sync helpers, as in
test_storage.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import retention
from app.services.retention import (
    STALE_PARTIAL_AFTER,
    PurgeRunner,
    StoredUploadPurge,
    get_purge_runner,
    purge_expired_data,
)

NOW = datetime.now(UTC)
RETENTION = timedelta(days=30)
CUTOFF = NOW - RETENTION
DAY = 86400.0


def put(directory: Path, name: str, age_days: float, *, age_seconds: float = 0.0) -> Path:
    """A file last changed that long ago (measured from now, not the cutoff)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"upload")
    then = time.time() - age_days * DAY - age_seconds
    os.utime(path, (then, then))
    return path


def remaining(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def exists(path: Path) -> bool:
    return path.exists()


# -- the purge of stored uploads ----------------------------------------------------


def test_the_purge_is_named_for_the_runner_to_list() -> None:
    assert StoredUploadPurge(Path(".")).name == "stored-uploads"


async def test_files_older_than_the_cutoff_are_deleted_and_counted(tmp_path: Path) -> None:
    put(tmp_path, "old-1.pdf", 40)
    put(tmp_path, "old-2.pdf", 90)

    removed = await StoredUploadPurge(tmp_path).purge(CUTOFF, 100)

    assert removed == 2
    assert remaining(tmp_path) == []


async def test_files_newer_than_the_cutoff_are_left(tmp_path: Path) -> None:
    put(tmp_path, "old.pdf", 40)
    put(tmp_path, "recent.pdf", 5)
    put(tmp_path, "today.pdf", 0)

    removed = await StoredUploadPurge(tmp_path).purge(CUTOFF, 100)

    assert removed == 1
    assert remaining(tmp_path) == ["recent.pdf", "today.pdf"]


async def test_at_most_limit_files_go_per_call_and_the_oldest_go_first(tmp_path: Path) -> None:
    for days in (35, 50, 45, 60, 40):
        put(tmp_path, f"{days}-days.pdf", days)

    removed = await StoredUploadPurge(tmp_path).purge(CUTOFF, 3)

    assert removed == 3
    # The three oldest (60, 50, 45) went; the two youngest candidates stay.
    assert remaining(tmp_path) == ["35-days.pdf", "40-days.pdf"]


async def test_a_limit_of_zero_deletes_nothing(tmp_path: Path) -> None:
    put(tmp_path, "old.pdf", 40)

    assert await StoredUploadPurge(tmp_path).purge(CUTOFF, 0) == 0
    assert remaining(tmp_path) == ["old.pdf"]


async def test_an_abandoned_partial_upload_goes_after_a_day_even_if_newer_than_the_cutoff(
    tmp_path: Path,
) -> None:
    assert STALE_PARTIAL_AFTER == timedelta(hours=24)
    put(tmp_path, "abandoned.pdf.part", 0, age_seconds=DAY + 3600)

    removed = await StoredUploadPurge(tmp_path).purge(CUTOFF, 100)

    assert removed == 1
    assert remaining(tmp_path) == []


async def test_a_fresh_partial_upload_is_left_because_a_request_may_be_writing_it(
    tmp_path: Path,
) -> None:
    put(tmp_path, "writing.pdf.part", 0, age_seconds=3600)
    put(tmp_path, "just-now.pdf.part", 0)

    removed = await StoredUploadPurge(tmp_path).purge(CUTOFF, 100)

    assert removed == 0
    assert remaining(tmp_path) == ["just-now.pdf.part", "writing.pdf.part"]


async def test_a_whole_file_a_day_old_is_not_treated_as_a_partial_upload(
    tmp_path: Path,
) -> None:
    put(tmp_path, "yesterday.pdf", 0, age_seconds=DAY + 3600)

    assert await StoredUploadPurge(tmp_path).purge(CUTOFF, 100) == 0
    assert remaining(tmp_path) == ["yesterday.pdf"]


async def test_sub_directories_and_what_is_in_them_are_ignored(tmp_path: Path) -> None:
    nested = tmp_path / "old-folder"
    put(nested, "inside.pdf", 90)
    then = time.time() - 90 * DAY
    os.utime(nested, (then, then))

    removed = await StoredUploadPurge(tmp_path).purge(CUTOFF, 100)

    assert removed == 0
    assert exists(nested / "inside.pdf")


async def test_a_directory_that_does_not_exist_has_nothing_to_purge(tmp_path: Path) -> None:
    assert await StoredUploadPurge(tmp_path / "never-made").purge(CUTOFF, 100) == 0


async def test_an_empty_directory_has_nothing_to_purge(tmp_path: Path) -> None:
    assert await StoredUploadPurge(tmp_path).purge(CUTOFF, 100) == 0


async def test_repeated_calls_drain_the_directory(tmp_path: Path) -> None:
    for number in range(7):
        put(tmp_path, f"old-{number}.pdf", 40 + number)
    put(tmp_path, "keep.pdf", 1)
    purge = StoredUploadPurge(tmp_path)

    counts = [await purge.purge(CUTOFF, 3) for _ in range(4)]

    assert counts == [3, 3, 1, 0]
    assert remaining(tmp_path) == ["keep.pdf"]


async def test_the_runner_calls_it_until_the_directory_is_clear(tmp_path: Path) -> None:
    for number in range(7):
        put(tmp_path, f"old-{number}.pdf", 40 + number)
    put(tmp_path, "keep.pdf", 1)
    runner = PurgeRunner(retention=lambda: RETENTION, clock=lambda: NOW, batch_size=2, pause=0)
    runner.register(StoredUploadPurge(tmp_path))

    report = await runner.run()

    assert report.deleted == {"stored-uploads": 7}
    assert report.failed == ()
    assert report.interrupted is False
    assert remaining(tmp_path) == ["keep.pdf"]


async def test_the_runner_leaves_the_directory_alone_when_a_class_is_running(
    tmp_path: Path,
) -> None:
    put(tmp_path, "old.pdf", 40)
    runner = PurgeRunner(retention=lambda: RETENTION, busy=lambda: True, clock=lambda: NOW)
    runner.register(StoredUploadPurge(tmp_path))

    report = await runner.run()

    assert report.interrupted is True
    assert remaining(tmp_path) == ["old.pdf"]


# -- the process's runner, and the scheduled run -------------------------------------


def test_the_process_runner_purges_the_upload_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    get_purge_runner.cache_clear()
    monkeypatch.setattr(retention, "get_settings", lambda: Settings(_env_file=None))
    try:
        assert get_purge_runner().task_names == ["stored-uploads"]
    finally:
        get_purge_runner.cache_clear()


async def test_the_process_runner_gives_way_while_a_class_is_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.realtime.classroom import classroom

    put(tmp_path, "old.pdf", 400)
    get_purge_runner.cache_clear()
    monkeypatch.setattr(
        retention,
        "get_settings",
        lambda: Settings(_env_file=None, upload_storage_dir=str(tmp_path)),
    )
    monkeypatch.setattr(type(classroom), "running_count", property(lambda self: 1))
    try:
        report = await get_purge_runner().run()
    finally:
        get_purge_runner.cache_clear()

    assert report.interrupted is True
    assert remaining(tmp_path) == ["old.pdf"]


async def test_a_scheduled_run_that_runs_out_of_time_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every batch it finished stays deleted and the next run carries on,
    so running out of time is not a failure of the job."""

    class Slow:
        async def run(self) -> None:
            await asyncio.sleep(10)

    monkeypatch.setattr(
        retention,
        "get_settings",
        lambda: Settings(_env_file=None, retention_purge_timeout_minutes=0.0005),
    )
    monkeypatch.setattr(retention, "get_purge_runner", lambda: Slow())

    with caplog.at_level(logging.WARNING, logger="clip.retention"):
        assert await purge_expired_data() is None

    assert "the next run continues" in caplog.text


async def test_a_scheduled_run_returns_what_it_deleted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    put(tmp_path, "old.pdf", 400)
    runner = PurgeRunner(retention=lambda: RETENTION, clock=lambda: NOW, pause=0)
    runner.register(StoredUploadPurge(tmp_path))
    monkeypatch.setattr(retention, "get_purge_runner", lambda: runner)

    report = await purge_expired_data()

    assert report is not None and report.deleted == {"stored-uploads": 1}
