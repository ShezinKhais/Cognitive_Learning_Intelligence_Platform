"""Runs housekeeping on a timer, off the request path and out of a live class's way.

Owner: General CS, Phase 7 (#65).

Each job is an async function the scheduler calls every so often until the app
stops. The app lifespan starts it and stops it, as it does the gateway and the
material processor.

- **Never overlaps itself.** A job runs to the end before its next wait
  starts, so a slow run delays the next one rather than doubling up.
- **Never takes the app down.** A job that raises is logged and tried again at
  its next turn.
- **Never blocks a class.** Live sessions share this event loop, so a job must
  await its database work and run anything CPU-bound in a thread
  (asyncio.to_thread), as report rendering does.

One process runs the schedule, as one process runs the live classes: production
already refuses more than one worker (Classroom.check_wiring).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

log = logging.getLogger("clip.scheduler")


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    every: timedelta
    run: Callable[[], Awaitable[object]]
    # The wait before the first run, so startup is not spent on housekeeping.
    first_after: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.every <= timedelta(0):
            raise ValueError(f"{self.name}: a job must wait between runs")


class Scheduler:
    def __init__(self, jobs: Sequence[ScheduledJob]) -> None:
        names = [job.name for job in jobs]
        if len(set(names)) != len(names):
            raise ValueError(f"job names must be unique: {names}")
        self.jobs = tuple(jobs)
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._keep_running(job), name=f"scheduled-{job.name}")
            for job in self.jobs
        ]

    async def stop(self) -> None:
        """Cancel every job, including one halfway through a run."""
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _keep_running(self, job: ScheduledJob) -> None:
        await asyncio.sleep(job.first_after.total_seconds())
        while True:
            await run_once(job)
            await asyncio.sleep(job.every.total_seconds())


async def run_once(job: ScheduledJob) -> bool:
    """Run a job one time. False when it failed; the failure is logged."""
    try:
        await job.run()
    except Exception:
        log.exception("scheduled job %s failed", job.name)
        return False
    return True
