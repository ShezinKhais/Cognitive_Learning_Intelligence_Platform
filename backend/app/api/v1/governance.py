"""Governance routes: deletion requests, the audit log and the retention purge.

Owner: BBIS, Phase 7. Admin only. The rules live in the services; these routes
translate them to HTTP and pass on who is asking and from where, so every step
lands in the audit log.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    Paginated,
    require_consents,
    require_roles,
)
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionError_,
    ValidationError,
)
from app.history.database import resolve_history_factory
from app.history.repository import list_for_student
from app.repositories import audit_repository
from app.schemas.common import Page
from app.schemas.governance import (
    AuditEntryOut,
    DeletionRequestCreate,
    DeletionRequestOut,
    HistoryOut,
    HistorySummaryOut,
    RetentionReportOut,
    RetentionRunRequest,
)
from app.schemas.identity import ConsentType, Role
from app.services import deletion_requests, retention
from app.services.deletion_requests import (
    AlreadyOpen,
    RequestNotFound,
    SelfApproval,
    TargetNotFound,
    WrongState,
)

router = APIRouter(
    prefix="/governance",
    tags=["governance"],
    dependencies=[
        Depends(require_roles(Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@contextmanager
def _translated() -> Iterator[None]:
    """Turn what the services refuse into the API's standard errors."""
    try:
        yield
    except (RequestNotFound, TargetNotFound) as error:
        raise NotFoundError(str(error)) from error
    except (AlreadyOpen, WrongState) as error:
        raise ConflictError(str(error)) from error
    except SelfApproval as error:
        raise PermissionError_(str(error)) from error
    except ValueError as error:
        raise ValidationError(str(error)) from error


def _report(report: retention.PurgeReport, days: int) -> RetentionReportOut:
    return RetentionReportOut(
        cutoff=report.cutoff,
        dry_run=report.dry_run,
        retention_days=days,
        sessions=report.sessions,
        answers=report.answers,
        roster_syncs=report.roster_syncs,
    )


# -- deletion requests ------------------------------------------------------------


@router.post(
    "/deletion-requests",
    response_model=DeletionRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_deletion_request(
    payload: DeletionRequestCreate,
    request: Request,
    principal: CurrentUser,
    db: DbSession,
) -> DeletionRequestOut:
    """Ask for a session's or a student's data to be erased. Nothing is deleted
    until a different admin approves the request and it is executed."""
    with _translated():
        created = await deletion_requests.create_request(
            db,
            target_type=payload.target_type,
            target_id=payload.target_id,
            requested_by=principal.user_id,
            reason=payload.reason,
        )
    return DeletionRequestOut.model_validate(created)


@router.get("/deletion-requests", response_model=Page[DeletionRequestOut])
async def list_deletion_requests(
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[
        Literal["requested", "approved", "rejected", "executed"] | None,
        Query(alias="status"),
    ] = None,
) -> Page[DeletionRequestOut]:
    rows, total = await deletion_requests.list_requests(
        db, status=status_filter, limit=page.limit, offset=page.offset
    )
    return Page[DeletionRequestOut](
        items=[DeletionRequestOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/deletion-requests/{request_id}", response_model=DeletionRequestOut)
async def get_deletion_request(request_id: UUID, db: DbSession) -> DeletionRequestOut:
    with _translated():
        found = await deletion_requests.get_request(db, request_id)
    return DeletionRequestOut.model_validate(found)


@router.post("/deletion-requests/{request_id}/approve", response_model=DeletionRequestOut)
async def approve_deletion_request(
    request_id: UUID, request: Request, principal: CurrentUser, db: DbSession
) -> DeletionRequestOut:
    """Approve a request. The admin who made it cannot approve it."""
    with _translated():
        decided = await deletion_requests.approve(db, request_id, admin_id=principal.user_id)
    return DeletionRequestOut.model_validate(decided)


@router.post("/deletion-requests/{request_id}/reject", response_model=DeletionRequestOut)
async def reject_deletion_request(
    request_id: UUID, request: Request, principal: CurrentUser, db: DbSession
) -> DeletionRequestOut:
    with _translated():
        decided = await deletion_requests.reject(db, request_id, admin_id=principal.user_id)
    return DeletionRequestOut.model_validate(decided)


@router.post("/deletion-requests/{request_id}/execute", response_model=DeletionRequestOut)
async def execute_deletion_request(
    request_id: UUID, request: Request, principal: CurrentUser, db: DbSession
) -> DeletionRequestOut:
    """Carry out an approved request. Deleting a session removes everything it
    holds and cannot be undone. Erasing a student deletes their own data and
    anonymises their account."""
    with _translated():
        done = await deletion_requests.execute(db, request_id, admin_id=principal.user_id)
    return DeletionRequestOut.model_validate(done)


# -- audit log --------------------------------------------------------------------


@router.get("/audit-log", response_model=Page[AuditEntryOut])
async def list_audit_log(
    db: DbSession,
    page: Paginated,
    action_type: Annotated[str | None, Query(max_length=100)] = None,
    user_id: UUID | None = None,
    target_type: Annotated[str | None, Query(max_length=50)] = None,
    target_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditEntryOut]:
    """The audit log, newest first. Entries are never deleted, by retention or
    by a deletion request."""
    rows, total = await audit_repository.list_events(
        db,
        limit=page.limit,
        offset=page.offset,
        action_type=action_type,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        since=since,
        until=until,
    )
    return Page[AuditEntryOut](
        items=[AuditEntryOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# -- retention --------------------------------------------------------------------


@router.get("/retention/preview", response_model=RetentionReportOut)
async def preview_retention(db: DbSession, settings: AppSettings) -> RetentionReportOut:
    """What the retention purge would delete right now. Deletes nothing."""
    days = settings.data_retention_days
    report = await retention.purge_expired(db, dry_run=True, retention_days=days)
    return _report(report, days)


@router.post("/retention/run", response_model=RetentionReportOut)
async def run_retention(
    payload: RetentionRunRequest,
    request: Request,
    principal: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> RetentionReportOut:
    """Purge every session past the retention period, and the Teams roster
    syncs past it. Cannot be undone, so the body must say `"confirm": true`.
    Audited with the counts."""
    days = settings.data_retention_days
    report = await retention.purge_expired(
        db,
        dry_run=False,
        retention_days=days,
        actor_id=principal.user_id,
    )
    return _report(report, days)


# -- history ----------------------------------------------------------------------


@router.get("/history/{student_id}", response_model=HistoryOut)
async def read_history(
    student_id: UUID, request: Request, principal: CurrentUser, db: DbSession
) -> HistoryOut:
    """The summaries kept for a student after their session data was deleted.
    Counts and averages only. Every read is audited."""
    factory = resolve_history_factory()
    if factory is None:
        return HistoryOut(enabled=False, summaries=[])
    async with factory() as history_db:
        rows = await list_for_student(history_db, student_id)
    await audit_repository.record_event(
        db,
        action_type="HISTORY_VIEWED",
        user_id=principal.user_id,
        target_type="student",
        target_id=student_id,
        details={"rows": len(rows)},
    )
    return HistoryOut(
        enabled=True,
        summaries=[
            HistorySummaryOut(
                semester=row.semester,
                course_id=row.course_id,
                sessions_attended=row.sessions_attended,
                questions_attempted=row.questions_attempted,
                questions_correct=row.questions_correct,
                engagement_average=(
                    row.engagement_sum / row.engagement_count if row.engagement_count else None
                ),
                gaze_average=row.gaze_sum / row.gaze_count if row.gaze_count else None,
            )
            for row in rows
        ],
    )
