"""Session reports, built off the request path so a live class never waits.

Owner: General CS, Phase 7 (#65).

`POST /sessions/{id}/reports` answers 202 with a report id at once. The report
is built here in the background: read from what the session stored (its
participation counts, its topics' difficulty and its alerts), then rendered as
a PDF in a thread. `GET /reports/{id}` says how far it has got and, once it is
ready, carries the report; `GET /reports/{id}/pdf` returns the file.

Not blocking a class:

- One report is built at a time (MAX_CONCURRENT_REPORTS). The rest queue.
- The database work is awaited, so the event loop is free while it waits.
- The PDF is rendered with asyncio.to_thread, since rendering is CPU-bound and
  would otherwise hold up every live session on this process.

Reports are kept in memory for REPORT_TTL after they finish, then dropped by
the scheduler; a lecturer who wants one later asks again. They are built from
stored data, so asking again gives the same report plus anything stored since.
Asking while one for the same session and person is still queued or running
returns that one. A report that a shutdown stops is marked failed with
INTERRUPTED, so nobody polls a report that will never finish.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol
from uuid import UUID, uuid4

from app.core.database import get_session_factory
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.repositories.live_event_repository import LiveEventRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.topic_difficulty_repository import DatabaseTopicAnswers
from app.schemas.report import (
    ReportJobOut,
    ReportParticipation,
    ReportStatus,
    SessionReport,
)
from app.schemas.session import SessionStatus, TopicDifficultyOut
from app.services import alert_store
from app.services.jobs import INTERNAL_ERROR, INTERRUPTED_ERROR
from app.services.report_pdf import render_pdf

log = logging.getLogger("clip.reports")

MAX_CONCURRENT_REPORTS = 1
REPORT_TTL = timedelta(hours=1)
# Kept at most, finished or not. A report asked for beyond this drops the
# oldest finished one; when none has finished, it is refused.
MAX_REPORTS = 200

FAILED_MESSAGE = "The report could not be built. Please try again."
INTERRUPTED_MESSAGE = "The report was stopped while the server was restarting. Please try again."


class ReportBuilder(Protocol):
    async def build(self, session_id: UUID) -> SessionReport: ...


class DatabaseReportBuilder:
    """Reads a session's report from what it stored, in a session of its own."""

    async def build(self, session_id: UUID) -> SessionReport:
        async with get_session_factory()() as db:
            sessions = SessionRepository(db)
            row = await sessions.get(session_id)
            if row is None:
                # Deleted, by the retention purge for example, after it was asked for.
                raise NotFoundError("Session was not found.", {"session_id": str(session_id)})
            counts = await LiveEventRepository(db).dashboard_counts(session_id)
            topics = await DatabaseTopicAnswers(db).session_topics(session_id)
            return SessionReport(
                session_id=session_id,
                course_code=await sessions.course_code(row.course_id),
                title=row.title,
                status=SessionStatus(row.status),
                starts_at=row.start_time,
                ended_at=row.ended_at,
                generated_at=_now(),
                participation=ReportParticipation(
                    students=counts.participants,
                    questions_delivered=counts.delivered_questions,
                    answers=counts.responses,
                    missed_answers=counts.missed_responses,
                    attention_prompts=counts.prompt_outcomes,
                ),
                topics=[TopicDifficultyOut.model_validate(t) for t in topics],
                alerts=await alert_store.list_session_alerts(db, session_id),
            )


@dataclass
class ReportJob:
    report_id: UUID
    session_id: UUID
    requested_by: UUID
    requested_at: datetime
    status: ReportStatus = ReportStatus.QUEUED
    finished_at: datetime | None = None
    error: str | None = None
    message: str | None = None
    report: SessionReport | None = None
    pdf: bytes | None = field(default=None, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in (ReportStatus.READY, ReportStatus.FAILED)

    def out(self) -> ReportJobOut:
        return ReportJobOut(
            report_id=self.report_id,
            session_id=self.session_id,
            status=self.status,
            requested_at=self.requested_at,
            finished_at=self.finished_at,
            error=self.error,
            message=self.message,
            report=self.report,
        )

    def end(
        self, status: ReportStatus, error: str | None = None, message: str | None = None
    ) -> None:
        self.status, self.error, self.message = status, error, message
        self.finished_at = _now()


class ReportQueue:
    def __init__(
        self,
        builder: ReportBuilder,
        render: Callable[[SessionReport], bytes] = render_pdf,
        max_concurrent: int = MAX_CONCURRENT_REPORTS,
    ) -> None:
        self._builder = builder
        self._render = render
        self._max_concurrent = max_concurrent
        self._jobs: dict[UUID, ReportJob] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._limit: asyncio.Semaphore | None = None
        self._limit_loop: asyncio.AbstractEventLoop | None = None

    def submit(self, session_id: UUID, requested_by: UUID) -> ReportJob:
        """Queue a report, or return the one this person already has on the way."""
        for job in self._jobs.values():
            if (job.session_id, job.requested_by) == (session_id, requested_by) and (
                not job.finished
            ):
                return job
        self._make_room()
        job = ReportJob(uuid4(), session_id, requested_by, requested_at=_now())
        self._jobs[job.report_id] = job
        task = asyncio.create_task(self._run(job), name=f"report-{job.report_id}")
        self._tasks[job.report_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job.report_id, None))
        return job

    def get(self, report_id: UUID) -> ReportJob | None:
        return self._jobs.get(report_id)

    def expire(self, now: datetime | None = None) -> int:
        """Drop reports finished more than REPORT_TTL ago. Returns how many."""
        cutoff = (now or _now()) - REPORT_TTL
        old = [
            job.report_id
            for job in self._jobs.values()
            if job.finished_at is not None and job.finished_at < cutoff
        ]
        for report_id in old:
            del self._jobs[report_id]
        return len(old)

    async def drain(self) -> None:
        """At shutdown: stop what is still queued or running, marking each
        INTERRUPTED, so nobody polls a report that will never finish."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job: ReportJob) -> None:
        try:
            async with self._slot():
                job.status = ReportStatus.RUNNING
                report = await self._builder.build(job.session_id)
                job.pdf = await asyncio.to_thread(self._render, report)
                job.report = report
                job.end(ReportStatus.READY)
        except asyncio.CancelledError:
            job.end(ReportStatus.FAILED, INTERRUPTED_ERROR, INTERRUPTED_MESSAGE)
            raise
        except Exception:
            log.exception("could not build report %s for session %s", job.report_id, job.session_id)
            job.end(ReportStatus.FAILED, INTERNAL_ERROR, FAILED_MESSAGE)

    def _make_room(self) -> None:
        if len(self._jobs) < MAX_REPORTS:
            return
        finished = sorted(
            (job for job in self._jobs.values() if job.finished),
            key=lambda job: job.finished_at or job.requested_at,
        )
        if not finished:
            raise ServiceUnavailableError(
                "Too many reports are being built. Please try again shortly.",
                {"limit": MAX_REPORTS},
            )
        del self._jobs[finished[0].report_id]

    def _slot(self) -> asyncio.Semaphore:
        # Per event loop, as BackgroundProcessor._slot explains: a semaphore
        # binds to the first loop that waits on it.
        loop = asyncio.get_running_loop()
        if self._limit is None or self._limit_loop is not loop:
            self._limit = asyncio.Semaphore(self._max_concurrent)
            self._limit_loop = loop
        return self._limit


@lru_cache
def get_report_queue() -> ReportQueue:
    return ReportQueue(DatabaseReportBuilder())


def _now() -> datetime:
    return datetime.now(UTC)
