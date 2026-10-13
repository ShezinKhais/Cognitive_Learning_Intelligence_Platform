"""Deletion requests: asking for data to be erased, and a second person agreeing.

Owner: BBIS, Phase 7. A request goes requested, then approved or rejected, then
executed. The admin who made a request cannot approve it. Every step writes an
audit entry, and the audit log and the request itself outlive what was deleted.

Executing a session request deletes the session, and the database removes
everything it holds. Executing a student request is not available yet: it waits
on the decision whether a student's answers are deleted or anonymised.

The caller owns the transaction and commits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deletion_request import DELETION_TARGETS, DeletionRequest
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.repositories.audit_repository import record_event

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


class StudentErasureUnavailable(DeletionRequestError):
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
    ip_address: str | None,
    **counts: Any,
) -> None:
    await record_event(
        db,
        action_type=action,
        user_id=actor,
        ip_address=ip_address,
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
    ip_address: str | None = None,
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
    db.add(request)
    await db.flush()
    await _audit(db, "DELETION_REQUESTED", request, requested_by, ip_address)
    return request


async def approve(
    db: AsyncSession,
    request_id: UUID,
    *,
    admin_id: UUID,
    ip_address: str | None = None,
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
    await _audit(db, "DELETION_APPROVED", request, admin_id, ip_address)
    return request


async def reject(
    db: AsyncSession, request_id: UUID, *, admin_id: UUID, ip_address: str | None = None
) -> DeletionRequest:
    request = await _locked(db, request_id)
    _require(request, "requested", "rejected")
    request.status = "rejected"
    request.decided_by = admin_id
    request.decided_at = datetime.now(UTC)
    await db.flush()
    await _audit(db, "DELETION_REJECTED", request, admin_id, ip_address)
    return request


async def execute(
    db: AsyncSession, request_id: UUID, *, admin_id: UUID, ip_address: str | None = None
) -> DeletionRequest:
    """Carry out an approved request. A session already gone, for example purged
    by retention, counts as done with nothing left to delete."""
    request = await _locked(db, request_id)
    _require(request, "approved", "executed")
    if request.target_type == "student":
        raise StudentErasureUnavailable("Erasing a student is not available yet.")

    sessions = (
        await db.scalar(
            select(func.count()).select_from(Session).where(Session.session_id == request.target_id)
        )
        or 0
    )
    answers = (
        await db.scalar(
            select(func.count())
            .select_from(StudentResponse)
            .where(StudentResponse.session_id == request.target_id)
        )
        or 0
    )
    await db.execute(delete(Session).where(Session.session_id == request.target_id))

    outcome = {"sessions": sessions, "answers": answers}
    request.status = "executed"
    request.executed_by = admin_id
    request.executed_at = datetime.now(UTC)
    request.outcome = outcome
    await db.flush()
    await _audit(db, "DELETION_EXECUTED", request, admin_id, ip_address, **outcome)
    return request
