"""Special consideration: the student's request and the administrator's decision.

Owner: General CS, Phase 8. See app.services.consideration.
"""

from __future__ import annotations

from typing import Literal
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
from app.core.audit import audit_action
from app.realtime.classroom import classroom
from app.schemas.common import Page
from app.schemas.consideration import (
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


async def _decide(
    request_id: UUID, approve: bool, payload: ConsiderationDecision, user_id: UUID, db: DbSession
) -> ConsiderationOut:
    decided, student_user = await consideration.decide(
        db, request_id, user_id, approve=approve, note=payload.note
    )
    await db.commit()
    if approve:
        # A student in a class right now is treated as accommodated from this
        # moment, not only from their next join.
        classroom.accommodations.set(student_user, True)
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
