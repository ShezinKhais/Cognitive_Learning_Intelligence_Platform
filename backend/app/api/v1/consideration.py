"""Special consideration: the student's request and the administrator's decision.

Owner: General CS, Phase 8. See app.services.consideration.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, Response, UploadFile, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    Paginated,
    require_consents,
    require_roles,
)
from app.core.audit import audit_action
from app.core.errors import NotFoundError, ValidationError
from app.models.consideration_request import ConsiderationRequest
from app.realtime.classroom import classroom
from app.schemas.common import Page
from app.schemas.consideration import (
    CapturePolicyOut,
    ConsiderationAdminOut,
    ConsiderationCreate,
    ConsiderationDecision,
    ConsiderationOut,
    MyConsiderationOut,
)
from app.schemas.identity import ConsentType, Role
from app.services import consideration

router = APIRouter()

mine = APIRouter(
    prefix="/me/consideration",
    tags=["consideration"],
    dependencies=[
        Depends(require_roles(Role.STUDENT)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)
admin = APIRouter(
    prefix="/admin/consideration-requests",
    tags=["consideration"],
    dependencies=[
        Depends(require_roles(Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@mine.get("", response_model=MyConsiderationOut)
async def my_request(principal: CurrentUser, db: DbSession) -> MyConsiderationOut:
    """The student's most recent request and where it stands."""
    return MyConsiderationOut(current=await consideration.my_request(db, principal.user_id))


@mine.get("/policy", response_model=CapturePolicyOut)
async def capture_policy(
    principal: CurrentUser, db: DbSession, response: Response
) -> CapturePolicyOut:
    response.headers["Cache-Control"] = "no-store"
    return CapturePolicyOut(
        camera_allowed=await consideration.capture_policy(db, principal.user_id)
    )


@mine.post("", response_model=ConsiderationOut, status_code=status.HTTP_201_CREATED)
@audit_action("CONSIDERATION_REQUESTED")
async def submit_request(
    payload: ConsiderationCreate,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> ConsiderationOut:
    """Ask for special consideration. One request may wait at a time (409)."""
    created = await consideration.submit(db, principal.user_id, payload)
    await db.commit()
    return created


MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
EVIDENCE_FORMATS = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}
DOWNLOAD_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


@mine.post("/with-evidence", response_model=ConsiderationOut, status_code=status.HTTP_201_CREATED)
@audit_action("CONSIDERATION_REQUESTED")
async def submit_with_evidence(
    payload: Annotated[str, Form(max_length=4096)],
    evidence: UploadFile,
    principal: CurrentUser,
    settings: AppSettings,
    db: DbSession,
) -> ConsiderationOut:
    """Submit one request and its supporting document in the same transaction."""
    try:
        details = ConsiderationCreate.model_validate_json(payload)
    except PydanticValidationError:
        raise ValidationError("Check the selected needs, end date and note.") from None

    file_format = EVIDENCE_FORMATS.get(PurePath(evidence.filename or "").suffix.lower())
    if file_format is None:
        raise ValidationError("Choose a PDF, PNG or JPEG file.")
    content_type, signature = file_format
    if evidence.size is not None and evidence.size > MAX_EVIDENCE_BYTES:
        raise ValidationError("Supporting evidence must be 5 MB or smaller.")
    content = await evidence.read(MAX_EVIDENCE_BYTES + 1)
    if len(content) > MAX_EVIDENCE_BYTES:
        raise ValidationError("Supporting evidence must be 5 MB or smaller.")
    if len(content) <= len(signature) or not content.startswith(signature):
        raise ValidationError("The file contents do not match the selected file type.")
    created = await consideration.submit(
        db, principal.user_id, details, evidence=content, evidence_type=content_type
    )
    await db.commit()
    return created


@mine.post("/withdraw", response_model=ConsiderationOut)
@audit_action("CONSIDERATION_WITHDRAWN")
async def withdraw_request(
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> ConsiderationOut:
    """Take back a request that is still waiting."""
    withdrawn = await consideration.withdraw(db, principal.user_id)
    await db.commit()
    return withdrawn


@admin.get("", response_model=Page[ConsiderationAdminOut])
async def list_requests(
    db: DbSession,
    page: Paginated,
    show: Literal["pending", "all"] = Query(default="pending"),
) -> Page[ConsiderationAdminOut]:
    """Requests to decide, oldest first; `show=all` adds the decided ones after them."""
    return await consideration.list_requests(
        db, pending_only=show == "pending", limit=page.limit, offset=page.offset
    )


@admin.get(
    "/{request_id}/evidence",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
@audit_action("CONSIDERATION_EVIDENCE_DOWNLOADED", commit=True)
async def download_evidence(
    request_id: UUID, principal: CurrentUser, settings: AppSettings, db: DbSession
) -> Response:
    """Download an attachment while the request is pending."""
    evidence = (
        await db.execute(
            select(ConsiderationRequest.evidence, ConsiderationRequest.evidence_type).where(
                ConsiderationRequest.request_id == request_id,
                ConsiderationRequest.status == "pending",
                ConsiderationRequest.evidence.is_not(None),
            )
        )
    ).one_or_none()
    if evidence is None:
        raise NotFoundError("Supporting evidence is unavailable.")
    content, content_type = evidence
    extension = DOWNLOAD_EXTENSIONS[content_type]
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="consideration-evidence{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _decide(
    request_id: UUID, approve: bool, payload: ConsiderationDecision, user_id: UUID, db: DbSession
) -> ConsiderationOut:
    decided, student_user = await consideration.decide(
        db, request_id, user_id, approve=approve, note=payload.note
    )
    await db.commit()
    if approve:
        # A student in a class right now is treated as accommodated from this
        # moment, not only from their next join, and only until its last day.
        classroom.accommodations.grant(student_user, decided.until)
    return decided


@admin.post("/{request_id}/approve", response_model=ConsiderationOut)
@audit_action("CONSIDERATION_APPROVED")
async def approve_request(
    request_id: UUID,
    payload: ConsiderationDecision,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> ConsiderationOut:
    """Approve a waiting request. The live class honours it at once."""
    return await _decide(request_id, True, payload, principal.user_id, db)


@admin.post("/{request_id}/reject", response_model=ConsiderationOut)
@audit_action("CONSIDERATION_REJECTED")
async def reject_request(
    request_id: UUID,
    payload: ConsiderationDecision,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> ConsiderationOut:
    """Refuse a waiting request. Nothing about the student changes."""
    return await _decide(request_id, False, payload, principal.user_id, db)


router.include_router(mine)
router.include_router(admin)
