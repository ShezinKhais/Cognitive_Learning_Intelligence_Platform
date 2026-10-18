"""Special consideration: a student asks, an administrator decides.

Owner: General CS, Phase 8. Approving a request records the accommodation on
the student, which the live class already honours: an accommodated student
is never sent a check-in prompt and never marked disengaged. Nothing about
the request beyond that fact reaches a lecturer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.consideration_request import ConsiderationRequest
from app.models.course import Course
from app.models.student import Student
from app.models.user import User
from app.repositories.student_repository import StudentRepository
from app.schemas.common import Page
from app.schemas.consideration import (
    ConsiderationAdminOut,
    ConsiderationCreate,
    ConsiderationOut,
)

# A request runs for at most this long; a longer need is asked for again.
MAX_DAYS = 366
# Written to student.accessibility_need on approval. Only its presence is read.
ACCOMMODATION_TEXT = "Special consideration"


def _out(row: ConsiderationRequest) -> ConsiderationOut:
    return ConsiderationOut(
        id=row.request_id,
        needs=row.needs,
        until=row.until,
        note=row.note,
        status=row.status,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
        decision_note=row.decision_note,
    )


async def _student(db: AsyncSession, user_id: UUID) -> Student:
    student = await StudentRepository(db).get_by_user_id(user_id)
    if student is None:
        raise NotFoundError("You are not enrolled on a course.", {})
    return student


async def _latest(db: AsyncSession, student_id: UUID) -> ConsiderationRequest | None:
    return await db.scalar(
        select(ConsiderationRequest)
        .where(ConsiderationRequest.student_id == student_id)
        .order_by(ConsiderationRequest.created_at.desc())
        .limit(1)
    )


async def my_request(db: AsyncSession, user_id: UUID) -> ConsiderationOut | None:
    row = await _latest(db, (await _student(db, user_id)).student_id)
    return _out(row) if row else None


async def submit(db: AsyncSession, user_id: UUID, payload: ConsiderationCreate) -> ConsiderationOut:
    student = await _student(db, user_id)
    today = datetime.now(UTC).date()
    if payload.until is not None and not today <= payload.until <= today + timedelta(MAX_DAYS):
        raise ValidationError("Choose a date from today to a year from now.", {"field": "until"})
    latest = await _latest(db, student.student_id)
    if latest is not None and latest.status == "pending":
        raise ConflictError("You already have a request waiting for a decision.", {})
    row = ConsiderationRequest(
        student_id=student.student_id,
        needs=[need.value for need in payload.needs],
        until=payload.until,
        note=payload.note,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _out(row)


async def withdraw(db: AsyncSession, user_id: UUID) -> ConsiderationOut:
    student = await _student(db, user_id)
    latest = await _latest(db, student.student_id)
    if latest is None or latest.status != "pending":
        raise ConflictError("There is no request waiting to withdraw.", {})
    latest.status = "withdrawn"
    await db.flush()
    return _out(latest)


async def list_requests(
    db: AsyncSession, *, pending_only: bool, limit: int, offset: int
) -> Page[ConsiderationAdminOut]:
    base = (
        select(ConsiderationRequest, User.name, User.email, Course.code)
        .join(Student, Student.student_id == ConsiderationRequest.student_id)
        .join(User, User.user_id == Student.user_id)
        .join(Course, Course.id == Student.course_id)
    )
    count = select(func.count()).select_from(ConsiderationRequest)
    if pending_only:
        base = base.where(ConsiderationRequest.status == "pending")
        count = count.where(ConsiderationRequest.status == "pending")
    rows = await db.execute(
        # Waiting ones first, oldest first, so nobody waits longest.
        base.order_by(
            (ConsiderationRequest.status != "pending"),
            ConsiderationRequest.created_at,
        )
        .limit(limit)
        .offset(offset)
    )
    items = [
        ConsiderationAdminOut(
            **_out(row).model_dump(), student_name=name, student_email=email, course_code=code
        )
        for row, name, email, code in rows.all()
    ]
    return Page(
        items=items, total=(await db.execute(count)).scalar_one(), limit=limit, offset=offset
    )


async def decide(
    db: AsyncSession, request_id: UUID, reviewer_id: UUID, *, approve: bool, note: str | None
) -> tuple[ConsiderationOut, UUID]:
    """Approve or refuse a waiting request. Returns it and the student's user
    id, so the caller can tell a class the student may be in right now."""
    row = await db.get(ConsiderationRequest, request_id, with_for_update=True)
    if row is None:
        raise NotFoundError("That request was not found.", {"request_id": str(request_id)})
    if row.status != "pending":
        raise ConflictError(f"This request was already {row.status}.", {"status": row.status})
    row.status = "approved" if approve else "rejected"
    row.reviewed_by = reviewer_id
    row.reviewed_at = datetime.now(UTC)
    row.decision_note = note.strip() or None if note else None
    student = await db.get(Student, row.student_id)
    assert student is not None
    if approve:
        student.special_consideration_status = "approved"
        # Kept if something is already recorded: that need is not this request's to replace.
        if not (student.accessibility_need or "").strip():
            student.accessibility_need = ACCOMMODATION_TEXT
    await db.flush()
    return _out(row), student.user_id
