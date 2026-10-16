"""Session reports: ask for one, follow it, download it.

Owner: General CS, Phase 7 (#65). Building happens in app/services/reports.py,
off the request path. Who may see a report is who may see the session's
analytics: the lecturer who runs it, or an admin. Anyone else, like a report
that does not exist or has expired, gets the same 404.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.api.v1.sessions import require_analytics_access
from app.core.audit import audit_action
from app.core.errors import ConflictError, NotFoundError
from app.schemas.identity import ConsentType, Role
from app.schemas.report import ReportJobOut, ReportStatus
from app.services.reports import ReportJob, get_report_queue

router = APIRouter(
    tags=["reports"],
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)

# A report describes a class, so it is never kept by a browser or a proxy.
_PRIVATE = {"Cache-Control": "no-store"}


@router.post(
    "/sessions/{session_id}/reports",
    response_model=ReportJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
@audit_action("REPORT_REQUESTED")
async def request_report(
    session_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
    response: Response,
) -> ReportJobOut:
    """Start building a report of the session, during it or after it. Answers
    at once; poll GET /reports/{report_id} until it is ready or failed. Asking
    again while yours is still being built returns the same report."""
    await require_analytics_access(db, principal, session_id)
    response.headers.update(_PRIVATE)
    return get_report_queue().submit(session_id, principal.user_id).out()


@router.get("/reports/{report_id}", response_model=ReportJobOut)
async def report_status(
    report_id: UUID, principal: CurrentUser, db: DbSession, response: Response
) -> ReportJobOut:
    """How far a report has got, and the report itself once it is ready."""
    job = await _viewable(report_id, principal, db)
    response.headers.update(_PRIVATE)
    return job.out()


@router.get(
    "/reports/{report_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The report as a PDF."}},
)
async def report_pdf(report_id: UUID, principal: CurrentUser, db: DbSession) -> Response:
    """The report as a PDF. 409 until it is ready."""
    job = await _viewable(report_id, principal, db)
    if job.status is not ReportStatus.READY or job.pdf is None or job.report is None:
        raise ConflictError("The report is not ready.", {"status": job.status.value})
    day = job.report.generated_at.strftime("%Y-%m-%d")
    return Response(
        content=job.pdf,
        media_type="application/pdf",
        headers={
            **_PRIVATE,
            "Content-Disposition": f'attachment; filename="clip-session-report-{day}.pdf"',
        },
    )


async def _viewable(report_id: UUID, principal: CurrentUser, db: DbSession) -> ReportJob:
    job = get_report_queue().get(report_id)
    if job is None:
        raise NotFoundError("Report was not found.", {"report_id": str(report_id)})
    try:
        await require_analytics_access(db, principal, job.session_id)
    except NotFoundError:
        # The same answer as a report that does not exist, so a report id
        # says nothing about a session the caller may not see.
        raise NotFoundError("Report was not found.", {"report_id": str(report_id)}) from None
    return job
