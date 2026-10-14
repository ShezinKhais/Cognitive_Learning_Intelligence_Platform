"""Housekeeping on a timer: the scheduler behind the stranded-material sweep and
report expiry.

Owner: General CS, Phase 7 (#65).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.main import housekeeping
from app.services.scheduler import ScheduledJob, Scheduler, run_once

TICK = timedelta(milliseconds=10)


async def test_a_job_runs_again_and_again_until_stopped() -> None:
    runs: list[int] = []

    async def job() -> None:
        runs.append(1)

    scheduler = Scheduler([ScheduledJob("count", TICK, job)])
    scheduler.start()
    await asyncio.sleep(0.08)
    await scheduler.stop()
    stopped_at = len(runs)
    await asyncio.sleep(0.05)

    assert stopped_at >= 3
    assert len(runs) == stopped_at


async def test_a_failing_job_is_logged_and_tried_again(caplog: pytest.LogCaptureFixture) -> None:
    runs: list[int] = []

    async def job() -> None:
        runs.append(1)
        raise RuntimeError("database is down")

    scheduler = Scheduler([ScheduledJob("flaky", TICK, job)])
    with caplog.at_level("ERROR", logger="clip.scheduler"):
        scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()

    assert len(runs) >= 2
    assert "scheduled job flaky failed" in caplog.text


async def test_a_slow_run_is_never_overlapped_by_the_next() -> None:
    running = 0
    most = 0

    async def job() -> None:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.03)
        running -= 1

    scheduler = Scheduler([ScheduledJob("slow", TICK, job)])
    scheduler.start()
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert most == 1


async def test_stopping_cancels_a_run_in_progress() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def job() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    scheduler = Scheduler([ScheduledJob("long", TICK, job)])
    scheduler.start()
    await started.wait()

    async with asyncio.timeout(1):
        await scheduler.stop()

    assert cancelled.is_set()


async def test_the_first_run_waits_when_asked_to() -> None:
    runs: list[int] = []

    async def job() -> None:
        runs.append(1)

    scheduler = Scheduler([ScheduledJob("later", TICK, job, first_after=timedelta(seconds=10))])
    scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert runs == []


async def test_jobs_run_independently() -> None:
    """One job stuck in a run does not hold up another."""
    quick: list[int] = []

    async def stuck() -> None:
        await asyncio.sleep(10)

    async def count() -> None:
        quick.append(1)

    scheduler = Scheduler([ScheduledJob("stuck", TICK, stuck), ScheduledJob("count", TICK, count)])
    scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert len(quick) >= 2


async def test_run_once_reports_whether_it_worked() -> None:
    async def fine() -> None:
        return None

    async def broken() -> None:
        raise ValueError("no")

    assert await run_once(ScheduledJob("fine", TICK, fine))
    assert not await run_once(ScheduledJob("broken", TICK, broken))


def test_a_job_must_wait_between_runs() -> None:
    async def job() -> None:
        return None

    with pytest.raises(ValueError, match="must wait"):
        ScheduledJob("busy", timedelta(0), job)


def test_two_jobs_cannot_share_a_name() -> None:
    async def job() -> None:
        return None

    with pytest.raises(ValueError, match="unique"):
        Scheduler([ScheduledJob("same", TICK, job), ScheduledJob("same", TICK, job)])


def test_the_app_schedules_its_housekeeping() -> None:
    assert [job.name for job in housekeeping().jobs] == [
        "stranded-material-sweep",
        "expire-reports",
    ]


async def test_the_report_expiry_job_expires_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    expired: list[int] = []

    class Queue:
        def expire(self) -> int:
            expired.append(1)
            return 0

    monkeypatch.setattr("app.main.get_report_queue", lambda: Queue())
    [job] = [j for j in housekeeping().jobs if j.name == "expire-reports"]

    assert await run_once(job)
    assert expired == [1]
