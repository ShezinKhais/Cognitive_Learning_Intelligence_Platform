"""Background processing coordination.

Owner: General CS, Phase 2.

The deliverable for this layer is that uploading does not block the API and
that no job ends without a word. A job reports its own outcome; what the
runner owes it is a bounded slot, and at shutdown a call to abandon() whether
the job was running or still queued, so it can tell the lecturer and the
database before the process goes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest

from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage
from app.services import jobs as jobs_module
from app.services.jobs import STAGE_PERCENT, BackgroundProcessor, JobStatus

EVENT_TIMEOUT_SECONDS = 5.0


async def _nothing() -> None:
    return None


class FakeJob:
    """A job whose work and interruption handling the test supplies."""

    def __init__(
        self,
        work: Callable[[], Awaitable[None]] = _nothing,
        on_abandon: Callable[[], Awaitable[None]] = _nothing,
    ) -> None:
        self.material_id: UUID = uuid4()
        self._work = work
        self._on_abandon = on_abandon
        self.abandoned = False

    async def run(self) -> None:
        await self._work()

    async def abandon(self) -> None:
        self.abandoned = True
        await self._on_abandon()


async def _forever() -> None:
    await asyncio.sleep(3600)


def _started_then_forever() -> tuple[asyncio.Event, Callable[[], Awaitable[None]]]:
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(3600)

    return started, work


async def test_submitting_does_not_wait_for_the_work() -> None:
    """The 202 must not be held open by a parser that takes eighteen seconds."""
    processor = BackgroundProcessor(max_concurrent=2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocks() -> None:
        started.set()
        await asyncio.wait_for(release.wait(), EVENT_TIMEOUT_SECONDS)

    task = processor.submit(FakeJob(blocks))

    # Control is back here while the job has not even begun.
    assert not started.is_set()

    await asyncio.wait_for(started.wait(), EVENT_TIMEOUT_SECONDS)
    release.set()
    await task


async def test_concurrency_is_bounded() -> None:
    """Ten parsers on four cores all finish later than four parsers would."""
    processor = BackgroundProcessor(max_concurrent=2)
    live = 0
    peak = 0

    async def tracked() -> None:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0)
        live -= 1

    await asyncio.gather(*[processor.submit(FakeJob(tracked)) for _ in range(8)])

    # Equal, not at most: no work running at all would also be at most two.
    assert peak == 2


async def test_a_job_that_raises_is_logged_and_does_not_stop_the_next(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The job has already reported its own failure; the traceback must not be lost."""
    processor = BackgroundProcessor(max_concurrent=1)
    ran_after = False

    async def explodes() -> None:
        raise RuntimeError("parser exploded")

    async def next_one() -> None:
        nonlocal ran_after
        ran_after = True

    failing = FakeJob(explodes)
    await processor.submit(failing)
    await processor.submit(FakeJob(next_one))

    assert ran_after
    assert not failing.abandoned
    assert any(str(failing.material_id) in record.message for record in caplog.records)


async def test_work_cancelled_at_shutdown_is_handed_back_to_the_job() -> None:
    processor = BackgroundProcessor(max_concurrent=1)
    started, work = _started_then_forever()
    job = FakeJob(work)

    processor.submit(job)
    await asyncio.wait_for(started.wait(), EVENT_TIMEOUT_SECONDS)
    await processor.drain(grace_seconds=0.01)

    assert job.abandoned
    assert processor.in_flight == 0


async def test_a_job_still_waiting_for_a_slot_is_abandoned_when_shutdown_cancels_it() -> None:
    """Waiting for the semaphore used to sit outside the handlers, so a queued
    job cancelled by a deploy skipped all of them and stayed pending forever."""
    processor = BackgroundProcessor(max_concurrent=1)
    holding, hog = _started_then_forever()

    async def never_gets_a_turn() -> None:
        raise AssertionError("a queued job must not run after shutdown")

    running = FakeJob(hog)
    queued = FakeJob(never_gets_a_turn)
    processor.submit(running)
    processor.submit(queued)
    await asyncio.wait_for(holding.wait(), EVENT_TIMEOUT_SECONDS)

    await processor.drain(grace_seconds=0.01)

    assert running.abandoned
    assert queued.abandoned


async def test_drain_lets_work_that_finishes_in_time_complete() -> None:
    """A nearly-complete parse should not be thrown away by a restart."""
    processor = BackgroundProcessor(max_concurrent=1)
    finished = False

    async def quick() -> None:
        nonlocal finished
        await asyncio.sleep(0)
        finished = True

    job = FakeJob(quick)
    processor.submit(job)
    await processor.drain(grace_seconds=5)

    assert finished
    assert not job.abandoned
    assert processor.in_flight == 0


async def test_drain_with_nothing_running_returns() -> None:
    processor = BackgroundProcessor(max_concurrent=1)
    await processor.drain(grace_seconds=0.01)


async def test_an_abandon_that_fails_does_not_stop_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The database being down during a deploy must not wedge the drain."""
    processor = BackgroundProcessor(max_concurrent=1)
    started, work = _started_then_forever()

    async def broken() -> None:
        raise ConnectionError("database is gone")

    job = FakeJob(work, on_abandon=broken)
    processor.submit(job)
    await asyncio.wait_for(started.wait(), EVENT_TIMEOUT_SECONDS)

    await processor.drain(grace_seconds=0.01)

    assert processor.in_flight == 0
    assert any("could not report the interruption" in r.message for r in caplog.records)


async def test_an_abandon_that_hangs_cannot_hold_shutdown_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """abandon() writes to the database. One that has stopped answering must
    not keep a deploy waiting."""
    monkeypatch.setattr(jobs_module, "ABANDON_TIMEOUT_SECONDS", 0.05)
    processor = BackgroundProcessor(max_concurrent=1)
    started, work = _started_then_forever()

    processor.submit(FakeJob(work, on_abandon=_forever))
    await asyncio.wait_for(started.wait(), EVENT_TIMEOUT_SECONDS)

    began = time.monotonic()
    await processor.drain(grace_seconds=0.01)

    assert time.monotonic() - began < 1.0
    assert processor.in_flight == 0


def test_the_concurrency_limit_works_on_a_second_event_loop() -> None:
    """The processor is a process-wide singleton. A semaphore bound to the
    first loop failed every queued job on the next one."""
    processor = BackgroundProcessor(max_concurrent=1)
    finished = 0

    async def brief() -> None:
        nonlocal finished
        await asyncio.sleep(0.01)
        finished += 1

    async def two_jobs_contending() -> None:
        await asyncio.gather(*(processor.submit(FakeJob(brief)) for _ in range(2)))

    asyncio.run(two_jobs_contending())
    asyncio.run(two_jobs_contending())

    assert finished == 4


def test_a_limit_of_zero_is_refused_rather_than_queueing_forever() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        BackgroundProcessor(max_concurrent=0)


def test_progress_is_monotonic_and_ends_at_one_hundred() -> None:
    """A bar that goes backwards reads as a bug even when nothing is wrong."""
    ordered = [
        MaterialStage.VALIDATING,
        MaterialStage.EXTRACTING,
        MaterialStage.CHUNKING,
        MaterialStage.EMBEDDING,
        MaterialStage.GENERATING,
        MaterialStage.DONE,
    ]
    percents = [STAGE_PERCENT[stage] for stage in ordered]

    assert percents == sorted(percents)
    assert percents[-1] == 100
    assert all(0 <= value <= 100 for value in STAGE_PERCENT.values())


def test_every_stage_in_the_frozen_contract_has_a_percent() -> None:
    """MaterialStage is part of events.schema.json, so it cannot drift silently."""
    assert set(STAGE_PERCENT) == set(MaterialStage)


def test_a_stage_maps_onto_the_reported_material_status() -> None:
    material_id = uuid4()

    def status_at(stage: MaterialStage) -> MaterialStatus:
        return JobStatus.for_stage(material_id, stage).status

    assert status_at(MaterialStage.CHUNKING) is MaterialStatus.PROCESSING
    assert status_at(MaterialStage.DONE) is MaterialStatus.COMPLETED
    assert status_at(MaterialStage.FAILED) is MaterialStatus.FAILED
