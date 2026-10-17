"""The retention rule: delete what a session left behind once it is old.

Owner: BBIS, Phase 7. A session ages from the day it ended (or, when it never
formally ended, its scheduled end or start). Once it is older than the retention
period the session row is deleted, and the database removes everything it holds:
answers and their labels, engagement, prompts, alerts, attention summaries and
so on. Lecturer questions and materials are content, not session data, so they
stay. Teams roster syncs hold participant names and outlive their session, so
they are purged on their own received date.

The audit log is never touched here. It is the record that this ran.

The caller owns the transaction and commits. A dry run only counts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.history.database import resolve_history_factory
from app.models.session import Session
from app.models.student_response import StudentResponse
from app.models.teams_roster_sync import TeamsRosterSync
from app.repositories.audit_repository import record_event

RETENTION_ACTION = "RETENTION_PURGE"

# Only a session that is over can be purged. A prepared, active or ending one is
# yet to start or still running, whatever its dates say, and is never deleted by
# retention. End it first. Sessions are archived to history in chunks this size.
TERMINAL_STATUSES = ("ended", "cancelled")
ARCHIVE_CHUNK = 500


@dataclass(frozen=True)
class PurgeReport:
    cutoff: datetime
    dry_run: bool
    sessions: int
    answers: int
    roster_syncs: int


def session_clock():
    """When a session's data started to age."""
    return func.coalesce(Session.ended_at, Session.end_time, Session.start_time)


def expired_sessions(cutoff: datetime):
    """The sessions retention may delete: over, and older than the cutoff."""
    return and_(session_clock() < cutoff, Session.status.in_(TERMINAL_STATUSES))


async def purge_expired(
    db: AsyncSession,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    retention_days: int | None = None,
    actor_id: UUID | None = None,
    ip_address: str | None = None,
    history: Callable[[], Any] | None = None,
) -> PurgeReport:
    """Purge, or with dry_run only count, everything past the retention period.

    A dry run is the default so that nothing is deleted by accident. A real run
    writes one audit entry with the counts, and nothing personal.
    """
    days = retention_days if retention_days is not None else get_settings().data_retention_days
    if days < 1:
        raise ValueError("The retention period must be at least one day")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)

    expired = expired_sessions(cutoff)
    old_syncs = TeamsRosterSync.received_at < cutoff

    sessions = await db.scalar(select(func.count()).select_from(Session).where(expired)) or 0
    answers = (
        await db.scalar(
            select(func.count())
            .select_from(StudentResponse)
            .where(StudentResponse.session_id.in_(select(Session.session_id).where(expired)))
        )
        or 0
    )
    roster_syncs = (
        await db.scalar(select(func.count()).select_from(TeamsRosterSync).where(old_syncs)) or 0
    )

    archived = None
    if not dry_run:
        # The same guarantee as the scheduled purge: what is kept goes to the
        # history database first, and if that fails nothing is deleted.
        factory = resolve_history_factory(history)
        if factory is not None:
            from app.services.history_archive import archive_sessions

            ids = list(await db.scalars(select(Session.session_id).where(expired)))
            archived = 0
            async with factory() as history_db:
                for start in range(0, len(ids), ARCHIVE_CHUNK):
                    archived += await archive_sessions(
                        db, history_db, ids[start : start + ARCHIVE_CHUNK]
                    )
                await history_db.commit()
        await db.execute(delete(Session).where(expired))
        await db.execute(delete(TeamsRosterSync).where(old_syncs))
        await record_event(
            db,
            action_type=RETENTION_ACTION,
            user_id=actor_id,
            ip_address=ip_address,
            target_type="retention",
            details={
                "sessions": sessions,
                "answers": answers,
                "roster_syncs": roster_syncs,
                "retention_days": days,
                "cutoff": cutoff.isoformat(),
                **({} if archived is None else {"archived_summaries": archived}),
            },
        )

    return PurgeReport(
        cutoff=cutoff,
        dry_run=dry_run,
        sessions=sessions,
        answers=answers,
        roster_syncs=roster_syncs,
    )
