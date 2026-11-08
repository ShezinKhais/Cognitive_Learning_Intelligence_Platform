"""Lecturers asking for new courses, and admins deciding.

Owner: General CS, Phase 8.

- A lecturer asks for a course by code and name, with an optional reason.
  A code that is already a course, or already waiting, is refused.
- An admin sees every request and approves or declines it. Approving
  creates the course, with any name correction, and makes the requester one
  of its lecturers. If an admin added the same code meanwhile, approving
  makes the requester a lecturer of that course instead.
- Declining keeps the request, with the admin's note, so the lecturer can
  see why.

A lecturer sees only their own requests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.course_request import CourseRequest
from app.models.user import User
from app.schemas.course_requests import (
    CourseRequestApprove,
    CourseRequestCreate,
    CourseRequestDecline,
    CourseRequestOut,
)
from app.schemas.identity import Role

# How many requests one listing returns. Plenty for a department.
LIST_LIMIT = 200


def _out(row: CourseRequest, requester: str | None) -> CourseRequestOut:
    out = CourseRequestOut.model_validate(row)
    out.requester_name = requester
    return out


async def create(
    db: AsyncSession, principal: Principal, payload: CourseRequestCreate
) -> CourseRequestOut:
    code = payload.code
    # Codes are compared ignoring case: older rows may not be upper case.
    if await db.scalar(select(Course.id).where(func.upper(Course.code) == code)):
        raise ConflictError(
            f"{code} is already a course. Ask an admin to add you as its lecturer.",
            {"code": code},
        )
    waiting = await db.scalar(
        select(CourseRequest.id).where(
            CourseRequest.code == code, CourseRequest.status == "pending"
        )
    )
    if waiting:
        raise ConflictError(f"{code} has already been asked for and is waiting.", {"code": code})
    reason = (payload.reason or "").strip() or None
    row = CourseRequest(
        code=code,
        name=payload.name.strip(),
        reason=reason,
        requested_by=principal.user_id,
        status="pending",
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        # Asked for at the same moment by someone else.
        await db.rollback()
        raise ConflictError(
            f"{code} has already been asked for and is waiting.", {"code": code}
        ) from exc
    await db.refresh(row)
    return _out(row, None)


async def list_for(
    db: AsyncSession, principal: Principal, status: str | None
) -> list[CourseRequestOut]:
    query = (
        select(CourseRequest, User.name)
        .join(User, User.user_id == CourseRequest.requested_by)
        .order_by(CourseRequest.created_at.desc())
        .limit(LIST_LIMIT)
    )
    if not principal.is_(Role.ADMIN):
        query = query.where(CourseRequest.requested_by == principal.user_id)
    if status:
        query = query.where(CourseRequest.status == status)
    return [_out(row, name) for row, name in (await db.execute(query)).all()]


async def _pending(db: AsyncSession, request_id: UUID) -> CourseRequest:
    row = await db.get(CourseRequest, request_id, with_for_update=True)
    if row is None:
        raise NotFoundError("That course request was not found.", {"request_id": str(request_id)})
    if row.status != "pending":
        raise ConflictError(
            f"That request was already {row.status}.",
            {"request_id": str(request_id), "status": row.status},
        )
    return row


async def approve(
    db: AsyncSession, principal: Principal, request_id: UUID, payload: CourseRequestApprove
) -> CourseRequestOut:
    row = await _pending(db, request_id)
    course = await db.scalar(select(Course).where(func.upper(Course.code) == row.code))
    if course is None:
        course = Course(code=row.code, name=(payload.name or row.name).strip())
        db.add(course)
        await db.flush()
    await db.execute(
        insert(CourseLecturer)
        .values(course_id=course.id, user_id=row.requested_by)
        .on_conflict_do_nothing()
    )
    row.status = "approved"
    row.course_id = course.id
    row.decided_by = principal.user_id
    row.decided_at = datetime.now(UTC)
    if payload.name:
        row.name = payload.name.strip()
    await db.commit()
    return await _with_name(db, row)


async def decline(
    db: AsyncSession, principal: Principal, request_id: UUID, payload: CourseRequestDecline
) -> CourseRequestOut:
    row = await _pending(db, request_id)
    row.status = "declined"
    row.decision_note = (payload.note or "").strip() or None
    row.decided_by = principal.user_id
    row.decided_at = datetime.now(UTC)
    await db.commit()
    return await _with_name(db, row)


async def _with_name(db: AsyncSession, row: CourseRequest) -> CourseRequestOut:
    await db.refresh(row)
    name = await db.scalar(select(User.name).where(User.user_id == row.requested_by))
    return _out(row, name)


async def rename_course(db: AsyncSession, code: str, name: str) -> Course:
    course = await db.scalar(select(Course).where(func.upper(Course.code) == code.upper()))
    if course is None:
        raise NotFoundError("No course has that code.", {"code": code})
    course.name = name.strip()
    await db.commit()
    await db.refresh(course)
    return course
