"""Runs material processing off the request path, and remembers how it went.

Owner: General CS, Phase 2.

`POST /api/v1/materials` answers 202 as soon as the file is on disk, so the
work itself has to happen somewhere else. That somewhere is here: a small
in-process runner holding a bounded number of concurrent jobs, plus a registry
of what each material's job is currently doing.

Bounded, because extraction is not cheap. Docling takes eighteen seconds on a
thirty-five page deck and pypdf fifteen, and both hold a CPU while they run.
Ten lecturers uploading at once with no ceiling means ten parsers competing for
the same cores, and every one of them finishes later than if they had queued.

In process, because this is a prototype serving one lecturer at a time. The
seam is drawn so that swapping in Celery or Azure Queue Storage later replaces
this file and nothing else: callers submit work and read status, and never
learn which of those it was.

The registry is memory only. A restart forgets what was in flight, which is why
the pipeline writes terminal state through to the database as well. Status that
has to survive a deploy is BBIS's table, not this dictionary.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

TERMINAL_STAGES = {MaterialStage.DONE, MaterialStage.FAILED}


@dataclass(frozen=True)
class JobStatus:
    """What a material's processing job is doing right now."""

    material_id: UUID
    status: MaterialStatus
    stage: MaterialStage
    percent: int
    message: str | None = None
    error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_finished(self) -> bool:
        return self.stage in TERMINAL_STAGES


def _status_for(stage: MaterialStage) -> MaterialStatus:
    if stage is MaterialStage.DONE:
        return MaterialStatus.COMPLETED
    if stage is MaterialStage.FAILED:
        return MaterialStatus.FAILED
    return MaterialStatus.PROCESSING


class JobRegistry:
    """Current state of every job this process knows about.

    Bounded for the same reason the hub's sequence map is: nothing deletes
    entries on a happy path, so without a ceiling a long-running process
    accumulates one record per upload forever. Finished jobs are evicted first,
    because a job still running needs its state far more than a completed one
    whose result is already in the database.
    """

    def __init__(self, max_entries: int = 4096) -> None:
        self._jobs: dict[UUID, JobStatus] = {}
        self._max_entries = max_entries

    def record(self, status: JobStatus) -> JobStatus:
        self._jobs[status.material_id] = status
        if len(self._jobs) > self._max_entries:
            self._evict_one()
        return status

    def advance(
        self,
        material_id: UUID,
        stage: MaterialStage,
        message: str | None = None,
        error: str | None = None,
    ) -> JobStatus:
        return self.record(
            JobStatus(
                material_id=material_id,
                status=_status_for(stage),
                stage=stage,
                percent=STAGE_PERCENT[stage],
                message=message,
                error=error,
            )
        )

    def get(self, material_id: UUID) -> JobStatus | None:
        return self._jobs.get(material_id)

    def forget(self, material_id: UUID) -> None:
        self._jobs.pop(material_id, None)

    def __len__(self) -> int:
        return len(self._jobs)

    def _evict_one(self) -> None:
        oldest_finished = min(
            (job for job in self._jobs.values() if job.is_finished),
            key=lambda job: job.updated_at,
            default=None,
        )
        if oldest_finished is not None:
            del self._jobs[oldest_finished.material_id]
            return

        # Everything on record is still running. Dropping a live job's status
        # would report "unknown material" for something actively processing, so
        # keep the oversized map and say why.
        log.warning(
            "%d material jobs are tracked and none has finished, so the %d ceiling "
            "cannot be enforced",
            len(self._jobs),
            self._max_entries,
        )


class BackgroundProcessor:
    """Accepts work, runs it later, and never lets a failure disappear."""

    def __init__(self, registry: JobRegistry, max_concurrent: int = 2) -> None:
        self._registry = registry
        self._limit = asyncio.Semaphore(max_concurrent)
        # Strong references to running tasks. asyncio only holds a weak one, so
        # a task nothing else references can be garbage collected mid-await and
        # the job vanishes with no error anywhere.
        self._running: set[asyncio.Task] = set()

    @property
    def in_flight(self) -> int:
        return len(self._running)

    def submit(
        self,
        material_id: UUID,
        work: Callable[[], Awaitable[None]],
    ) -> asyncio.Task:
        """Queue work and return immediately.

        The material is marked queued here rather than inside the task, so a
        status read between the 202 and the worker starting reports pending
        instead of "no such material".
        """
        self._registry.record(
            JobStatus(
                material_id=material_id,
                status=MaterialStatus.PENDING,
                stage=MaterialStage.VALIDATING,
                percent=0,
                message="Waiting for a processing slot.",
            )
        )

        task = asyncio.create_task(
            self._run(material_id, work),
            name=f"material-{material_id}",
        )
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        return task

    async def _run(
        self,
        material_id: UUID,
        work: Callable[[], Awaitable[None]],
    ) -> None:
        async with self._limit:
            try:
                await work()
            except asyncio.CancelledError:
                # Shutdown, not a bad file. Say so rather than blaming the
                # upload, and let the cancellation continue to propagate.
                self._registry.advance(
                    material_id,
                    MaterialStage.FAILED,
                    message="Processing was interrupted while the server was stopping.",
                    error="cancelled",
                )
                raise
            except Exception as exc:
                # The pipeline marks its own failures. Reaching here means
                # something outside it broke, and a job that ends with no
                # terminal state is a spinner that never stops.
                log.exception("processing material %s failed", material_id)
                current = self._registry.get(material_id)
                if current is None or not current.is_finished:
                    self._registry.advance(
                        material_id,
                        MaterialStage.FAILED,
                        message="Processing failed unexpectedly.",
                        error=type(exc).__name__,
                    )

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
