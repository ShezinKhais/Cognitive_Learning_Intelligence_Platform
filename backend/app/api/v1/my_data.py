"""A student's own data: take a copy, or ask for it to be erased.

Owner: BBIS, Phase 7. Students only. The deletion request goes through the same
service as the admin routes, so it needs a different admin to approve it, and
every step is audited there.

No consent is required. A student who has withdrawn the terms can still take a
copy of their data or ask for it to be erased: those are rights, not features.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.schemas.identity import Role
from app.schemas.my_data import MyDeletionRequestCreate, MyDeletionRequestOut, StudentDataExport
from app.services import deletion_requests, student_data
from app.services.deletion_requests import AlreadyOpen
from app.services.student_data import StudentNotFound

router = APIRouter(
    prefix="/me",
    tags=["my-data"],
    dependencies=[Depends(require_roles(Role.STUDENT))],
)


@router.get("/data", response_model=StudentDataExport)
async def export_my_data(
    request: Request, principal: CurrentUser, db: DbSession, response: Response
) -> dict:
    """Everything the platform keeps about you, as JSON."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="my-clip-data.json"'
    try:
        return await student_data.export_student_data(db, principal.user_id)
    except StudentNotFound as error:
        raise NotFoundError(str(error)) from error


@router.post(
    "/deletion-request",
    response_model=MyDeletionRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_my_deletion(
    payload: MyDeletionRequestCreate, request: Request, principal: CurrentUser, db: DbSession
) -> MyDeletionRequestOut:
    """Ask for your own data to be erased. Nothing is deleted until an admin
    approves the request and carries it out; erasing cannot be undone."""
    if not payload.confirm:
        raise ValidationError("Confirm that you understand your data will be erased for good.")
    try:
        student = await student_data.own_student(db, principal.user_id)
        created = await deletion_requests.create_request(
            db,
            target_type="student",
            target_id=student.student_id,
            requested_by=principal.user_id,
            reason=payload.reason,
        )
    except StudentNotFound as error:
        raise NotFoundError(str(error)) from error
    except AlreadyOpen as error:
        raise ConflictError(str(error)) from error
    return MyDeletionRequestOut.model_validate(created)


@router.get("/deletion-request", response_model=MyDeletionRequestOut)
async def my_deletion_request(principal: CurrentUser, db: DbSession) -> MyDeletionRequestOut:
    """Where your latest deletion request stands."""
    try:
        student = await student_data.own_student(db, principal.user_id)
    except StudentNotFound as error:
        raise NotFoundError(str(error)) from error
    found = await student_data.latest_deletion_request(db, student.student_id)
    if found is None:
        raise NotFoundError("You have not asked for your data to be deleted.")
    return MyDeletionRequestOut.model_validate(found)
