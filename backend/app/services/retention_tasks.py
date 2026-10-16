"""The database purge tasks, registered with the purge runner.

Owner: BBIS, Phase 7. The runner (purge_runner.py) owns when and how a purge
runs: oldest first, a batch at a time, giving way to a live class. These tasks
own what is deleted from the database, under the same rule as
`services/retention.py`: a session ages from the day it ended, deleting it
removes everything it holds, and Teams roster syncs age from the day they were
received. Each batch writes one audit entry with counts and nothing personal,
as the system. The audit log itself is never purged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_session_factory
from app.history.database import resolve_history_factory
from app.models.session import Session
from app.models.student_response import StudentResponse
from app.models.teams_roster_sync import TeamsRosterSync
from app.models.teams_user_mapping import TeamsUserMapping
from app.repositories.audit_repository import record_event
from app.services.history_archive import archive_sessions
from app.services.purge_runner import PurgeRunner
from app.services.retention import RETENTION_ACTION, session_clock

SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]


class SessionDataPurge:
    """Deletes sessions past the retention period, and with them the answers,
    labels, prompts, engagement and attention summaries they hold.

    When the history database is on, each batch is archived into it first, as
    derived summaries, and committed there. If that fails nothing is deleted,
    the runner logs the failure, and the next run tries the same sessions."""

    name = "session-data"

    def __init__(
        self,
        sessions: SessionFactory = get_session_factory,
        history: SessionFactory | None = None,
    ) -> None:
        self._sessions = sessions
        self._history = history

    def _history_factory(self) -> async_sessionmaker[AsyncSession] | None:
        return resolve_history_factory(self._history)

    async def purge(self, cutoff: datetime, limit: int) -> int:
        async with self._sessions()() as db:
            ids = list(
                await db.scalars(
                    select(Session.session_id)
                    .where(session_clock() < cutoff)
                    .order_by(session_clock())
                    .limit(limit)
                )
            )
            if not ids:
                return 0
            archived = None
            history = self._history_factory()
            if history is not None:
                async with history() as archive:
                    archived = await archive_sessions(db, archive, ids)
                    await archive.commit()
            answers = (
                await db.scalar(
                    select(func.count())
                    .select_from(StudentResponse)
                    .where(StudentResponse.session_id.in_(ids))
                )
                or 0
            )
            await db.execute(delete(Session).where(Session.session_id.in_(ids)))
            details = {
                "task": self.name,
                "sessions": len(ids),
                "answers": answers,
                "cutoff": cutoff.isoformat(),
            }
            if archived is not None:
                details["archived_summaries"] = archived
            await record_event(
                db,
                action_type=RETENTION_ACTION,
                user_id=None,
                target_type="retention",
                details=details,
            )
            await db.commit()
            return len(ids)


class RosterSyncPurge:
    """Deletes Teams roster syncs past the retention period. They hold
    participant names and outlive their session, so they age on their own date."""

    name = "teams-roster-syncs"

    def __init__(self, sessions: SessionFactory = get_session_factory) -> None:
        self._sessions = sessions

    async def purge(self, cutoff: datetime, limit: int) -> int:
        async with self._sessions()() as db:
            ids = list(
                await db.scalars(
                    select(TeamsRosterSync.sync_id)
                    .where(TeamsRosterSync.received_at < cutoff)
                    .order_by(TeamsRosterSync.received_at)
                    .limit(limit)
                )
            )
            if not ids:
                return 0
            await db.execute(delete(TeamsRosterSync).where(TeamsRosterSync.sync_id.in_(ids)))
            await record_event(
                db,
                action_type=RETENTION_ACTION,
                user_id=None,
                target_type="retention",
                details={
                    "task": self.name,
                    "roster_syncs": len(ids),
                    "cutoff": cutoff.isoformat(),
                },
            )
            await db.commit()
            return len(ids)


class TeamsMappingPurge:
    """Deletes Teams user mappings that were never matched to an account, once
    they are past the retention period. They hold Teams ids and belong to nobody.
    A mapping to a live account is kept, and cleared if that student is erased."""

    name = "teams-unresolved-mappings"

    def __init__(self, sessions: SessionFactory = get_session_factory) -> None:
        self._sessions = sessions

    async def purge(self, cutoff: datetime, limit: int) -> int:
        async with self._sessions()() as db:
            ids = list(
                await db.scalars(
                    select(TeamsUserMapping.mapping_id)
                    .where(TeamsUserMapping.user_id.is_(None), TeamsUserMapping.updated_at < cutoff)
                    .order_by(TeamsUserMapping.updated_at)
                    .limit(limit)
                )
            )
            if not ids:
                return 0
            await db.execute(delete(TeamsUserMapping).where(TeamsUserMapping.mapping_id.in_(ids)))
            await record_event(
                db,
                action_type=RETENTION_ACTION,
                user_id=None,
                target_type="retention",
                details={
                    "task": self.name,
                    "unresolved_mappings": len(ids),
                    "cutoff": cutoff.isoformat(),
                },
            )
            await db.commit()
            return len(ids)


def register_database_purges(runner: PurgeRunner) -> None:
    """Add the database purge tasks to the runner. Safe to call again."""
    for task in (SessionDataPurge(), RosterSyncPurge(), TeamsMappingPurge()):
        if task.name not in runner.task_names:
            runner.register(task)
