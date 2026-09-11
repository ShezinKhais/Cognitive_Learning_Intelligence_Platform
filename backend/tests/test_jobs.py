"""Background processing coordination.

Owner: General CS, Phase 2.

The deliverable for this layer is that uploading does not block the API and
that no job ever ends without saying how it ended. Most of what follows is
about the second half: a lecturer watching a spinner needs it to stop, whether
the parse succeeded, threw, or was killed by a deploy.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage
from app.services.jobs import (
    STAGE_PERCENT,
    BackgroundProcessor,
    JobRegistry,
    JobStatus,
)


async def test_submitting_does_not_wait_for_the_work() -> None:
    """The 202 must not be held open by a parser that takes eighteen seconds."""
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocks() -> None:
        started.set()
        await release.wait()

    material_id = uuid4()
    task = processor.submit(material_id, blocks)

    # Control is back here while the job has not even begun.
    assert not started.is_set()

    await started.wait()
    release.set()
    await task


async def test_a_queued_material_reports_pending_before_the_worker_starts() -> None:
    """A status read between the 202 and the worker must not 404."""
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=1)
    release = asyncio.Event()

    async def blocks() -> None:
        await release.wait()

    material_id = uuid4()
    task = processor.submit(material_id, blocks)

    status = registry.get(material_id)
    assert status is not None
    assert status.status is MaterialStatus.PENDING
    assert status.percent == 0

    release.set()
    await task


async def test_concurrency_is_bounded() -> None:
    """Ten parsers on four cores all finish later than four parsers would."""
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=2)
    live = 0
    peak = 0

    async def tracked() -> None:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0)
        live -= 1

    await asyncio.gather(*[processor.submit(uuid4(), tracked) for _ in range(8)])

    assert peak <= 2


async def test_a_job_that_raises_is_recorded_as_failed() -> None:
    """An exception with no terminal state is a spinner that never stops."""
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=1)

    async def explodes() -> None:
        raise RuntimeError("parser exploded")

    material_id = uuid4()
    await processor.submit(material_id, explodes)

    status = registry.get(material_id)
    assert status is not None
    assert status.status is MaterialStatus.FAILED
    assert status.stage is MaterialStage.FAILED
    assert status.error == "RuntimeError"
    assert status.is_finished


async def test_a_failure_the_pipeline_already_recorded_is_left_alone() -> None:
    """The pipeline knows which file was bad; the runner only backstops it."""
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=1)
    material_id = uuid4()

    async def fails_after_reporting() -> None:
        registry.advance(
            material_id,
            MaterialStage.FAILED,
            message="No readable text found in this file",
            error="ValidationError",
        )
        raise RuntimeError("and then the wrapper blew up too")

    await processor.submit(material_id, fails_after_reporting)

    status = registry.get(material_id)
    assert status is not None
    assert status.message == "No readable text found in this file"


async def test_work_cancelled_at_shutdown_is_marked_not_left_running() -> None:
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=1)
    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.sleep(3600)

    material_id = uuid4()
    processor.submit(material_id, never_finishes)
    await started.wait()

    await processor.drain(grace_seconds=0.01)

    status = registry.get(material_id)
    assert status is not None
    assert status.stage is MaterialStage.FAILED
    assert status.error == "cancelled"
    assert processor.in_flight == 0


async def test_drain_lets_work_that_finishes_in_time_complete() -> None:
    """A nearly-complete parse should not be thrown away by a restart."""
    registry = JobRegistry()
    processor = BackgroundProcessor(registry, max_concurrent=1)
    finished = False

    async def quick() -> None:
        nonlocal finished
        await asyncio.sleep(0)
        finished = True
        registry.advance(uuid4(), MaterialStage.DONE)

    processor.submit(uuid4(), quick)
    await processor.drain(grace_seconds=5)

    assert finished
    assert processor.in_flight == 0


async def test_drain_with_nothing_running_returns() -> None:
    processor = BackgroundProcessor(JobRegistry(), max_concurrent=1)
    await processor.drain(grace_seconds=0.01)


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


def test_advancing_maps_stages_onto_the_reported_status() -> None:
    registry = JobRegistry()
    material_id = uuid4()

    assert registry.advance(material_id, MaterialStage.CHUNKING).status is MaterialStatus.PROCESSING
    assert registry.advance(material_id, MaterialStage.DONE).status is MaterialStatus.COMPLETED
    assert registry.advance(material_id, MaterialStage.FAILED).status is MaterialStatus.FAILED


def test_the_registry_evicts_finished_jobs_before_running_ones() -> None:
    """Dropping a live job reports "unknown material" for active work."""
    registry = JobRegistry(max_entries=3)
    running = uuid4()
    registry.record(
        JobStatus(
            material_id=running,
            status=MaterialStatus.PROCESSING,
            stage=MaterialStage.EXTRACTING,
            percent=20,
        )
    )

    for _ in range(5):
        registry.advance(uuid4(), MaterialStage.DONE)

    assert len(registry) <= 3
    assert registry.get(running) is not None


def test_forgetting_a_job_removes_it() -> None:
    registry = JobRegistry()
    material_id = uuid4()
    registry.advance(material_id, MaterialStage.DONE)

    registry.forget(material_id)

    assert registry.get(material_id) is None
