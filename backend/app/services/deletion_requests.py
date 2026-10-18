"""Deletion requests: asking for data to be erased, and a second person agreeing.

Owner: BBIS, Phase 7. A request goes requested, then approved or rejected, then
executed. The admin who made a request cannot approve it. Every step writes an
audit entry, and the audit log and the request itself outlive what was deleted.

Executing a session request deletes the session, and the database removes
everything it holds. Executing a student request erases that student's own data
and anonymises their account (see student_erasure.py).

The caller owns the transaction and commits.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.database import resolve_history_factory
from app.history.repository import delete_student as delete_student_history
from app.models.deletion_request import DELETION_TARGETS, DeletionRequest
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.teams_roster_sync import TeamsRosterSync
from app.repositories.audit_repository import record_event
from app.services.retention import TERMINAL_STATUSES
from app.services.student_erasure import erase_student

MAX_REASON_LENGTH = 500
OPEN_STATUSES = ("requested", "approved")


class DeletionRequestError(Exception):
    """A deletion request cannot do what was asked."""


class RequestNotFound(DeletionRequestError):
    pass


class TargetNotFound(DeletionRequestError):
    pass


class AlreadyOpen(DeletionRequestError):
    pass


class WrongState(DeletionRequestError):
    pass


class SelfApproval(DeletionRequestError):
    pass


async def _target_exists(db: AsyncSession, target_type: str, target_id: UUID) -> bool:
    if target_type == "session":
        query = select(Session.session_id).where(Session.session_id == target_id)
    else:
        query = select(Student.student_id).where(Student.student_id == target_id)
    return await db.scalar(query) is not None


async def _locked(db: AsyncSession, request_id: UUID) -> DeletionRequest:
    """The request, locked so two admins cannot act on it at once."""
    request = await db.scalar(
        select(DeletionRequest).where(DeletionRequest.request_id == request_id).with_for_update()
    )
    if request is None:
        raise RequestNotFound("Deletion request not found.")
    return request


def _require(request: DeletionRequest, status: str, verb: str) -> None:
    if request.status != status:
        raise WrongState(f"A request that is {request.status} cannot be {verb}.")


async def _audit(
    db: AsyncSession,
    action: str,
    request: DeletionRequest,
    actor: UUID,
    **counts: Any,
) -> None:
    await record_event(
        db,
        action_type=action,
        user_id=actor,
        target_type=request.target_type,
        target_id=request.target_id,
        details={"request_id": str(request.request_id), **counts},
    )


async def get_request(db: AsyncSession, request_id: UUID) -> DeletionRequest:
    request = await db.scalar(
        select(DeletionRequest).where(DeletionRequest.request_id == request_id)
    )
    if request is None:
        raise RequestNotFound("Deletion request not found.")
    return request


async def list_requests(
    db: AsyncSession, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[DeletionRequest], int]:
    """A page of requests, newest first, and how many matched in all."""
    query = select(DeletionRequest)
    if status is not None:
        query = query.where(DeletionRequest.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(
        query.order_by(DeletionRequest.requested_at.desc(), DeletionRequest.request_id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars().all()), total


async def create_request(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: UUID,
    requested_by: UUID,
    reason: str | None = None,
) -> DeletionRequest:
    if target_type not in DELETION_TARGETS:
        raise ValueError(f"target_type must be one of {', '.join(DELETION_TARGETS)}")
    reason = (reason or "").strip() or None
    if reason is not None and len(reason) > MAX_REASON_LENGTH:
        raise ValueError(f"A reason must be at most {MAX_REASON_LENGTH} characters")
    if not await _target_exists(db, target_type, target_id):
        raise TargetNotFound(f"No {target_type} with that id.")
    already = await db.scalar(
        select(DeletionRequest.request_id).where(
            DeletionRequest.target_type == target_type,
            DeletionRequest.target_id == target_id,
            DeletionRequest.status.in_(OPEN_STATUSES),
        )
    )
    if already is not None:
        raise AlreadyOpen(f"This {target_type} already has an open deletion request.")

    request = DeletionRequest(
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        requested_by=requested_by,
    )
    # The check above is not enough on its own: two requests filed at the same
    # moment both pass it. The unique index on open requests is what refuses
    # the second, and the savepoint keeps the caller's transaction usable.
    try:
        async with db.begin_nested():
            db.add(request)
    except IntegrityError as error:
        raise AlreadyOpen(f"This {target_type} already has an open deletion request.") from error
    await _audit(db, "DELETION_REQUESTED", request, requested_by)
    return request


async def approve(
    db: AsyncSession,
    request_id: UUID,
    *,
    admin_id: UUID,
    allow_self_approval: bool = False,
) -> DeletionRequest:
    request = await _locked(db, request_id)
    _require(request, "requested", "approved")
    if request.requested_by == admin_id and not allow_self_approval:
        raise SelfApproval("The admin who made a request cannot approve it.")
    request.status = "approved"
    request.decided_by = admin_id
    request.decided_at = datetime.now(UTC)
    await db.flush()
    await _audit(db, "DELETION_APPROVED", request, admin_id)
    return request


async def reject(db: AsyncSession, request_id: UUID, *, admin_id: UUID) -> DeletionRequest:
    request = await _locked(db, request_id)
    _require(request, "requested", "rejected")
    request.status = "rejected"
    request.decided_by = admin_id
    request.decided_at = datetime.now(UTC)
    await db.flush()
    await _audit(db, "DELETION_REJECTED", request, admin_id)
    return request


async def _delete_session(db: AsyncSession, session_id: UUID) -> dict[str, int]:
    """Delete a finished session and everything it holds, including the Teams
    roster snapshots that name its participants, which would otherwise outlive it
    until the roster purge. A session that is still running is refused: deleting it
    mid-class would pull it out from under the answers still arriving."""
    status = await db.scalar(select(Session.status).where(Session.session_id == session_id))
    if status is not None and status not in TERMINAL_STATUSES:
        raise WrongState("A session that has not ended or been cancelled cannot be deleted.")
    sessions = (
        await db.scalar(
            select(func.count()).select_from(Session).where(Session.session_id == session_id)
        )
        or 0
    )
    answers = (
        await db.scalar(
            select(func.count())
            .select_from(StudentResponse)
            .where(StudentResponse.session_id == session_id)
        )
        or 0
    )
    roster_syncs = await db.execute(
        delete(TeamsRosterSync).where(TeamsRosterSync.session_id == session_id)
    )
    await db.execute(delete(Session).where(Session.session_id == session_id))
    return {"sessions": sessions, "answers": answers, "roster_syncs": roster_syncs.rowcount or 0}


async def _erase_history(student_id: UUID, history: Callable[[], Any] | None) -> int | None:
    """Erase the student's rows in the history database, and commit there.
    None when history is off. A failure propagates, so the request is not marked
    executed and can be run again."""
    factory = resolve_history_factory(history)
    if factory is None:
        return None
    async with factory() as history_db:
        removed = await delete_student_history(history_db, student_id)
        await history_db.commit()
    return removed


async def execute(
    db: AsyncSession,
    request_id: UUID,
    *,
    admin_id: UUID,
    history: Callable[[], Any] | None = None,
) -> DeletionRequest:
    """Carry out an approved request. Something already gone, for example a
    session purged by retention, counts as done with nothing left to delete."""
    request = await _locked(db, request_id)
    _require(request, "approved", "executed")

    if request.target_type == "student":
        history_rows = await _erase_history(request.target_id, history)
        outcome = (await erase_student(db, request.target_id)).as_counts()
        if history_rows is not None:
            outcome["history_rows"] = history_rows
    else:
        outcome = await _delete_session(db, request.target_id)

    request.status = "executed"
    request.executed_by = admin_id
    request.executed_at = datetime.now(UTC)
    request.outcome = outcome
    await db.flush()
    await _audit(db, "DELETION_EXECUTED", request, admin_id, **outcome)
    return request
