"""The purge runner: deletes what has outlived its retention period.

Owner: General CS, Phase 7 (#65), for the runner. BBIS owns what is deleted
from the database, and registers a purge task here for each kind of it with
`get_purge_runner().register(task)`. The task General CS owns, for the
upload files this process writes, is StoredUploadPurge below.

The README promises that session data is deleted after DATA_RETENTION_DAYS.
A promise like that is kept by something that runs without being asked, so
the scheduler runs this once a day (main.housekeeping).

Deleting is done by purge tasks. Each one knows one kind of data and deletes
a bounded batch of it, oldest first. The runner calls a task again and again
until it has nothing left, and between batches it stops to let everything
else in the process run. That is what keeps a purge of a term's worth of data
from holding a database lock, or the event loop, for as long as it takes: no
batch is large, and a class that starts halfway through a purge is not kept
waiting for the end of it. The runner stops early when a session starts, or
when its time is up, and the next run carries on from where it left off,
since every task deletes oldest first.

A task that raises is logged and skipped. The others still run.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger("clip.retention")

# Rows or files one call to a task may delete.
BATCH_SIZE = 500
# The pause between batches, for everything else the process is doing.
BATCH_PAUSE_SECONDS = 0.05
# The most batches one task gets in one run. With the batch size above this
# is a quarter of a million items, far more than a day accumulates, and it
# stops a task that never reports itself empty.
MAX_BATCHES_PER_TASK = 500
# An upload still under its temporary name after this long was abandoned by a
# request that died: a whole upload takes seconds.
STALE_PARTIAL_AFTER = timedelta(hours=24)


class PurgeTask(Protocol):
    """Deletes one kind of data that is past its retention period.

    `purge` deletes at most `limit` items last changed before `cutoff`,
    oldest first, commits, and returns how many it deleted. Returning fewer
    than `limit` says there is nothing left. It is called repeatedly, so it
    must not hold anything open between calls.
    """

    name: str

    async def purge(self, cutoff: datetime, limit: int) -> int: ...


@dataclass(frozen=True)
class PurgeReport:
    """What one run deleted, by task, and how it ended."""

    cutoff: datetime
    deleted: dict[str, int] = field(default_factory=dict)
    failed: tuple[str, ...] = ()
    # Stopped before every task was empty: a session started, or time ran out.
    interrupted: bool = False

    @property
    def total(self) -> int:
        return sum(self.deleted.values())

    def summary(self) -> str:
        if not self.deleted and not self.failed:
            return "no purge task is registered"
        parts = [f"{name}: {count}" for name, count in sorted(self.deleted.items())]
        line = f"deleted {self.total} item(s) older than {self.cutoff:%Y-%m-%d}"
        if parts:
            line += " (" + ", ".join(parts) + ")"
        if self.failed:
            line += "; failed: " + ", ".join(self.failed)
        if self.interrupted:
            line += "; stopped early, the next run continues"
        return line


class PurgeRunner:
    def __init__(
        self,
        retention: Callable[[], timedelta],
        busy: Callable[[], bool] = lambda: False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch_size: int = BATCH_SIZE,
        pause: float = BATCH_PAUSE_SECONDS,
    ) -> None:
        self._retention = retention
        self._busy = busy
        self._clock = clock
        self._batch_size = batch_size
        self._pause = pause
        self._tasks: dict[str, PurgeTask] = {}

    def register(self, task: PurgeTask) -> None:
        if task.name in self._tasks:
            raise ValueError(f"A purge task named {task.name} is already registered")
        self._tasks[task.name] = task

    @property
    def task_names(self) -> list[str]:
        return sorted(self._tasks)

    async def run(self) -> PurgeReport:
        """Delete everything past the retention period, a batch at a time,
        stopping between batches as soon as a session is running."""
        retention = self._retention()
        if retention <= timedelta(0):
            # A retention of zero would delete everything there is. It is a
            # misconfiguration, not an instruction.
            raise ValueError("The retention period must be above zero")
        cutoff = self._clock() - retention
        deleted: dict[str, int] = {}
        failed: list[str] = []
        interrupted = False
        for name in self.task_names:
            task = self._tasks[name]
            count = 0
            yielded = False
            try:
                for _ in range(MAX_BATCHES_PER_TASK):
                    if self._busy():
                        yielded = True
                        break
                    removed = await task.purge(cutoff, self._batch_size)
                    count += max(removed, 0)
                    if removed < self._batch_size:
                        break
                    await asyncio.sleep(self._pause)
                else:
                    # Still not empty. The other tasks get their turn, and
                    # this one carries on in the next run.
                    interrupted = True
            except Exception:
                log.exception("purge task %s failed", name)
                failed.append(name)
            deleted[name] = count
            if yielded:
                # A class has started. Nothing more is deleted in this run.
                interrupted = True
                break
        report = PurgeReport(
            cutoff=cutoff, deleted=deleted, failed=tuple(failed), interrupted=interrupted
        )
        # One line a governance review can find: what was deleted, and when.
        log.info("retention_purge %s", report.summary())
        return report


class StoredUploadPurge:
    """Deletes lecture files left in upload storage past the retention period.

    A file is deleted from storage as soon as its material has been processed,
    or has failed for a reason no retry can fix. What stays behind is the file
    of a material that failed in a way that might have been temporary, kept
    in case it is tried again, and nothing ever comes back for those. Also
    deletes an upload abandoned under its temporary name, after a day.
    """

    name = "stored-uploads"

    def __init__(self, directory: Path) -> None:
        self._directory = directory.resolve()

    async def purge(self, cutoff: datetime, limit: int) -> int:
        return await asyncio.to_thread(self._purge, cutoff.timestamp(), limit)

    def _purge(self, cutoff: float, limit: int) -> int:
        if not self._directory.is_dir():
            return 0
        stale_partial = time.time() - STALE_PARTIAL_AFTER.total_seconds()
        candidates = []
        for path in self._directory.iterdir():
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                changed = path.stat().st_mtime
            except OSError:
                continue
            if changed < cutoff or (path.name.endswith(".part") and changed < stale_partial):
                candidates.append((changed, path))
        removed = 0
        # Oldest first, so a run that is cut short has dealt with the files
        # that have waited longest.
        for _, path in sorted(candidates, key=lambda item: item[0])[:limit]:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                log.warning("could not delete the stored upload %s", path.name)
        return removed


def _class_is_running() -> bool:
    # Imported here: the classroom imports half the application, and the
    # runner does not need it until it runs.
    from app.realtime.classroom import classroom

    return classroom.running_count > 0


@lru_cache
def get_purge_runner() -> PurgeRunner:
    """The process's purge runner, with the upload purge registered. It gives
    way between batches whenever a class is running."""
    runner = PurgeRunner(
        retention=lambda: timedelta(days=get_settings().data_retention_days),
        busy=_class_is_running,
    )
    runner.register(StoredUploadPurge(Path(get_settings().upload_storage_dir)))
    return runner


async def purge_expired_data() -> PurgeReport | None:
    """One scheduled run, held to RETENTION_PURGE_TIMEOUT_MINUTES. A run cut
    off by the limit has deleted only whole batches, and the next carries on,
    so running out of time is reported and is not a failure. None then."""
    minutes = get_settings().retention_purge_timeout_minutes
    try:
        return await asyncio.wait_for(get_purge_runner().run(), timeout=minutes * 60)
    except TimeoutError:
        log.warning("retention_purge stopped after %.0f minutes; the next run continues", minutes)
        return None
