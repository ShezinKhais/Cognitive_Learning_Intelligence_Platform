"""Writes and reads the audit log.

Owner: BBIS, Phase 7. Each function works inside the caller's transaction and
does not commit. Entries are never updated or deleted here, and nothing in
retention or student deletion touches this table.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

MAX_ACTION_LENGTH = 100
MAX_DETAIL_TEXT = 200


def checked_details(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Details are counts, flags and short identifiers, never personal content.

    Only flat values are accepted, so an answer, a name or a whole record cannot
    be dropped in by accident.
    """
    if details is None:
        return None
    clean: dict[str, Any] = {}
    for key, value in details.items():
        if not isinstance(value, str | int | float | bool | None):
            raise ValueError(f"Audit detail {key!r} must be a number, a flag or short text")
        if isinstance(value, str) and len(value) > MAX_DETAIL_TEXT:
            raise ValueError(f"Audit detail {key!r} is longer than {MAX_DETAIL_TEXT} characters")
        clean[str(key)] = value
    return clean


async def record_event(
    db: AsyncSession,
    *,
    action_type: str,
    user_id: UUID | None = None,
    ip_address: str | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    details: Mapping[str, Any] | None = None,
) -> AuditLog:
    """Add one audit entry to the caller's transaction.

    Leave user_id empty for something the system did on its own.
    """
    if not action_type or len(action_type) > MAX_ACTION_LENGTH:
        raise ValueError(f"action_type must be 1 to {MAX_ACTION_LENGTH} characters")
    entry = AuditLog(
        user_id=user_id,
        action_type=action_type,
        ip_address=ip_address,
        target_type=target_type,
        target_id=target_id,
        details=checked_details(details),
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_events(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    action_type: str | None = None,
    user_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[AuditLog], int]:
    """A page of audit entries, newest first, and how many matched in all."""
    query = select(AuditLog)
    if action_type is not None:
        query = query.where(AuditLog.action_type == action_type)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if target_type is not None:
        query = query.where(AuditLog.target_type == target_type)
    if target_id is not None:
        query = query.where(AuditLog.target_id == target_id)
    if since is not None:
        query = query.where(AuditLog.timestamp >= since)
    if until is not None:
        query = query.where(AuditLog.timestamp < until)

    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(
        query.order_by(AuditLog.timestamp.desc(), AuditLog.log_id).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total
