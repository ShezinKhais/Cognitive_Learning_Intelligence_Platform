"""Course rosters: which students are on a course and who teaches it.

Owner: General CS, Phase 8. Students see only the classes of the courses
they are on, so this is where that is decided. An admin manages every
course and its lecturers; a lecturer manages the students of the courses
they teach. Every change is audited.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.schemas.accounts import CourseLecturersSet, CourseOut, CourseRoster, RosterStudentAdd
from app.schemas.course_requests import CourseRequestCreate, CourseRequestOut, CourseRequestStatus
from app.schemas.identity import ConsentType, Role
from app.services import course_membership, course_requests

router = APIRouter(
    prefix="/courses",
    tags=["courses"],
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@router.post("/requests", response_model=CourseRequestOut, status_code=status.HTTP_201_CREATED)
@audit_action("COURSE_REQUESTED")
async def request_course(
    payload: CourseRequestCreate,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> CourseRequestOut:
    """Ask an admin for a course that does not exist yet."""
    return await course_requests.create(db, principal, payload)


@router.get("/requests", response_model=list[CourseRequestOut])
async def list_course_requests(
    principal: CurrentUser,
    db: DbSession,
    status_filter: Annotated[CourseRequestStatus | None, Query(alias="status")] = None,
) -> list[CourseRequestOut]:
    """A lecturer's own requests, or every request for an admin, newest first."""
    return await course_requests.list_for(db, principal, status_filter)


@router.get("/mine", response_model=list[CourseOut])
async def my_courses(principal: CurrentUser, db: DbSession) -> list[CourseOut]:
    """The courses the caller manages: those they teach, or every course for
    an admin."""
    return await course_membership.my_courses(db, principal)


@router.get("/{code}/roster", response_model=CourseRoster)
async def get_roster(code: str, principal: CurrentUser, db: DbSession) -> CourseRoster:
    """The course's lecturers and the students on it."""
    return await course_membership.roster(db, principal, code)


@router.post("/{code}/students", response_model=CourseRoster)
@audit_action("COURSE_STUDENT_ADDED")
async def add_student(
    code: str,
    payload: RosterStudentAdd,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> CourseRoster:
    """Put an existing student account on this course, by email."""
    await course_membership.add_student(db, principal, code, payload.email)
    await db.commit()
    return await course_membership.roster(db, principal, code)


@router.delete("/{code}/students/{user_id}", response_model=CourseRoster)
@audit_action("COURSE_STUDENT_REMOVED")
async def remove_student(
    code: str,
    user_id: UUID,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> CourseRoster:
    """Take a student off this course. They stop seeing its classes."""
    await course_membership.remove_student(db, principal, code, user_id)
    await db.commit()
    return await course_membership.roster(db, principal, code)


@router.put("/{code}/lecturers", response_model=CourseRoster)
@audit_action("COURSE_LECTURERS_SET")
async def set_lecturers(
    code: str,
    payload: CourseLecturersSet,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> CourseRoster:
    """Admin only: who teaches this course."""
    await course_membership.set_lecturers(db, principal, code, payload.lecturer_ids)
    await db.commit()
    return await course_membership.roster(db, principal, code)
