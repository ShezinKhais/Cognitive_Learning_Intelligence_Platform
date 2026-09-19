"""Runs material processing off the request path.

Owner: General CS, Phase 2.

`POST /api/v1/materials` answers 202 as soon as the file is on disk, so the
work itself has to happen somewhere else. That somewhere is here: a small
in-process runner holding a bounded number of concurrent jobs.

Bounded, because extraction is not cheap. Docling takes eighteen seconds on a
thirty-five page deck and pypdf fifteen, and both hold a CPU while they run.
Ten lecturers uploading at once with no ceiling means ten parsers competing for
the same cores, and every one of them finishes later than if they had queued.

In process, because this is a prototype serving one lecturer at a time. The
seam is drawn so that swapping in Celery or Azure Queue Storage later replaces
this file and nothing else: callers submit a job and never learn which of those
ran it.

The runner keeps no record of how a job went. A job reports its own progress to
the lecturer and its own outcome to the store; the runner's one duty beyond
running it is to hand an interrupted job back to itself at shutdown, which is
the only moment nobody else is watching.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage

log = logging.getLogger("clip.jobs")

# How far through the whole pipeline each stage is considered to be when it
# starts. Progress has to be monotonic and land on 100 exactly once, so the
# numbers live in one place rather than being sprinkled through the pipeline.
STAGE_PERCENT: dict[MaterialStage, int] = {
    MaterialStage.VALIDATING: 5,
    MaterialStage.EXTRACTING: 20,
    MaterialStage.CHUNKING: 55,
    MaterialStage.EMBEDDING: 70,
    MaterialStage.GENERATING: 90,
    MaterialStage.DONE: 100,
    MaterialStage.FAILED: 100,
}

# What a lecturer is told when a deploy stops their upload.
INTERRUPTED_MESSAGE = "Processing was interrupted while the server was stopping."

# What a lecturer is told when processing raises something nobody anticipated.
UNEXPECTED_FAILURE_MESSAGE = "Processing failed unexpectedly."

# Machine-readable codes for JobStatus.error, in the same UPPER_SNAKE form as
# the API's error envelope. The lecturer-facing text is JobStatus.message; an
# exception class name is an implementation detail and belongs in the log.
INTERRUPTED_ERROR = "INTERRUPTED"
INTERNAL_ERROR = "INTERNAL_ERROR"

# How long an interrupted job may take to record itself at shutdown. It tells
# the lecturer and writes to the database, and a deploy must not wait
# indefinitely on either; a database that has stopped answering would otherwise
# hold the process open.
ABANDON_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class JobStatus:
    """Where a material's processing has got to."""

    material_id: UUID
    status: MaterialStatus
    stage: MaterialStage
    percent: int
    message: str | None = None
    error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def for_stage(
        cls,
        material_id: UUID,
        stage: MaterialStage,
        message: str | None = None,
        error: str | None = None,
    ) -> JobStatus:
        """The status a material holds once it reaches `stage`."""
        return cls(
            material_id=material_id,
            status=stage.material_status,
            stage=stage,
            percent=STAGE_PERCENT[stage],
            message=message,
            error=error,
        )


class Job(Protocol):
    """One unit of background work, which knows how to end itself.

    `abandon` is called instead of letting `run` finish when a shutdown stops
    the job, whether it was halfway through or still waiting for a slot. It is
    the job's one chance to tell the lecturer and the database, since nothing
    in this process survives the restart.
    """

    material_id: UUID

    async def run(self) -> object: ...

    async def abandon(self) -> None: ...


class BackgroundProcessor:
    """Accepts jobs, runs them later, and never lets one end without a word."""

    def __init__(self, max_concurrent: int = 2) -> None:
        # Zero is accepted by Semaphore and queues every job forever with no
        # error anywhere, so it is refused here rather than discovered later.
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be at least 1, got {max_concurrent}")
        self._max_concurrent = max_concurrent
        self._limit: asyncio.Semaphore | None = None
        self._limit_loop: asyncio.AbstractEventLoop | None = None
        # Strong references to running tasks. asyncio only holds a weak one, so
        # a task nothing else references can be garbage collected mid-await and
        # the job vanishes with no error anywhere.
        # Keyed by task, so the material each one is working on is known.
        self._running: dict[asyncio.Task, UUID] = {}

    @property
    def in_flight(self) -> int:
        return len(self._running)

    @property
    def active_material_ids(self) -> frozenset[UUID]:
        """Materials this process is still working on, queued ones included."""
        return frozenset(self._running.values())

    def submit(self, job: Job) -> asyncio.Task:
        """Queue a job and return immediately."""
        task = asyncio.create_task(self._run(job), name=f"material-{job.material_id}")
        self._running[task] = job.material_id
        task.add_done_callback(lambda done: self._running.pop(done, None))
        return task

    async def _run(self, job: Job) -> None:
        # Waiting for a slot is inside the try. A job cancelled while still
        # queued raises from the semaphore, and outside the try that skipped
        # the abandon below and left the material pending forever.
        try:
            async with self._slot():
                await job.run()
        except asyncio.CancelledError:
            await self._abandon(job)
            raise
        except Exception:
            # The job reports its own failures before raising, so all that is
            # left to do with one is make sure the traceback is not lost.
            log.exception("processing material %s failed", job.material_id)

    async def _abandon(self, job: Job) -> None:
        """Hand a job stopped by shutdown back to itself, within a bound."""
        try:
            async with asyncio.timeout(ABANDON_TIMEOUT_SECONDS):
                await job.abandon()
        except Exception:
            log.exception("could not report the interruption of material %s", job.material_id)

    def _slot(self) -> asyncio.Semaphore:
        """The concurrency limit for the loop this job is running on.

        The processor is a process-wide singleton, and a Semaphore binds itself
        to the first loop that has to wait on it. A second loop in the same
        process, as a test run or a reloaded app produces, then failed every
        job that queued with "bound to a different event loop". Built per loop,
        each gets its own.
        """
        loop = asyncio.get_running_loop()
        if self._limit is None or self._limit_loop is not loop:
            self._limit = asyncio.Semaphore(self._max_concurrent)
            self._limit_loop = loop
        return self._limit

    async def drain(self, grace_seconds: float = 30.0) -> None:
        """Wait for in-flight work at shutdown, then cancel what is left.

        Called from the app lifespan. Without it a deploy kills the event loop
        mid-parse and the lecturer's upload is stuck at 20 per cent with no
        record of why.

        This is a grace period rather than a deadline on the whole call: work
        that finishes inside it is left alone, and only the overrun is
        cancelled, so a nearly-complete parse is not thrown away.
        """
        if not self._running:
            return

        pending = list(self._running)
        log.info("waiting for %d material job(s) to finish", len(pending))
        _done, still_running = await asyncio.wait(pending, timeout=grace_seconds)

        for task in still_running:
            task.cancel()
        if still_running:
            log.warning("cancelled %d material job(s) that overran shutdown", len(still_running))
            await asyncio.gather(*still_running, return_exceptions=True)
