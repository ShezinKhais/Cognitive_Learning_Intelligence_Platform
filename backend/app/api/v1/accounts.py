"""Admin account management: people, their roles, courses and access.

Owner: General CS. Admins only, with the terms accepted, like the other
/admin routes. Every change is audited. These are the database accounts
production signs in with; in development, sign-in still uses the built-in
accounts.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.schemas.accounts import (
    AccountCreate,
    AccountIssued,
    AccountOut,
    AccountUpdate,
    CourseCreate,
    CourseOut,
)
from app.schemas.common import Page
from app.schemas.identity import ConsentType, Role
from app.services import accounts

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[
        Depends(require_roles(Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@router.get("/accounts", response_model=Page[AccountOut])
async def list_accounts(
    db: DbSession,
    role: Role | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AccountOut]:
    """Everyone with an account, staff first, filtered by role or by a part
    of their name or email."""
    items, total = await accounts.list_accounts(db, role=role, query=q, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/accounts", response_model=AccountIssued, status_code=status.HTTP_201_CREATED)
@audit_action("ACCOUNT_CREATED")
async def create_account(
    payload: AccountCreate,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
    response: Response,
) -> AccountIssued:
    """Add a person. A student needs a course. A website password, when
    asked for, is returned this once."""
    response.headers["Cache-Control"] = "no-store"
    account, password = await accounts.create_account(db, payload)
    return AccountIssued(account=account, password=password)


@router.patch("/accounts/{user_id}", response_model=AccountOut)
@audit_action("ACCOUNT_UPDATED")
async def update_account(
    user_id: UUID,
    payload: AccountUpdate,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> AccountOut:
    """Rename, switch on or off, swap lecturer and admin, or move a student
    to another course. A switched-off account cannot sign in."""
    return await accounts.update_account(db, principal.user_id, user_id, payload)


@router.post("/accounts/{user_id}/password", response_model=AccountIssued)
@audit_action("ACCOUNT_PASSWORD_RESET")
async def reset_password(
    user_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
    response: Response,
) -> AccountIssued:
    """Issue a new website password, returned this once. The old one stops
    working at once."""
    response.headers["Cache-Control"] = "no-store"
    account, password = await accounts.reset_password(db, user_id)
    return AccountIssued(account=account, password=password)


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(db: DbSession) -> list[CourseOut]:
    """Courses a student can be enrolled on."""
    return await accounts.list_courses(db)


@router.post("/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
@audit_action("COURSE_CREATED")
async def create_course(
    payload: CourseCreate,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> CourseOut:
    """Add a course by its code and name."""
    return await accounts.create_course(db, payload)
