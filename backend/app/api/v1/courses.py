"""Course rosters: which students are on a course and who teaches it.

Owner: General CS, Phase 8. Students see only the classes of the courses
they are on, so this is where that is decided. An admin manages every
course and its lecturers; a lecturer manages the students of the courses
they teach. Every change is audited.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.api.deps import AppSettings, CurrentUser, DbSession, require_consents, require_roles
from app.core.audit import audit_action
from app.schemas.accounts import CourseLecturersSet, CourseOut, CourseRoster, RosterStudentAdd
from app.schemas.attendance import CourseAttendanceOut
from app.schemas.identity import ConsentType, Role
from app.services import attendance, course_membership

router = APIRouter(
    prefix="/courses",
    tags=["courses"],
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


@router.get("/mine", response_model=list[CourseOut])
async def my_courses(principal: CurrentUser, db: DbSession) -> list[CourseOut]:
    """The courses the caller manages: those they teach, or every course for
    an admin."""
    return await course_membership.my_courses(db, principal)


@router.get("/{code}/attendance", response_model=CourseAttendanceOut)
async def course_attendance(
    code: str, principal: CurrentUser, db: DbSession
) -> CourseAttendanceOut:
    """Who attended each finished class of the course, oldest first."""
    course = await course_membership._course(db, code)
    await course_membership._may_manage(db, principal, course)
    return await attendance.course_attendance(db, course)


@router.get(
    "/{code}/attendance.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
@audit_action("COURSE_ATTENDANCE_EXPORTED")
async def course_attendance_csv(
    code: str, principal: CurrentUser, request: Request, settings: AppSettings, db: DbSession
) -> Response:
    """The same as a CSV, one row per student and one column per class."""
    course = await course_membership._course(db, code)
    await course_membership._may_manage(db, principal, course)
    body = attendance.course_csv(await attendance.course_attendance(db, course))
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="attendance-{course.code}.csv"',
            "Cache-Control": "no-store",
        },
    )


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
