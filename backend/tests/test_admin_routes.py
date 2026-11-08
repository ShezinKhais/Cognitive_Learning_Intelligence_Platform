"""Integration tests for the administrator console routes.

Owner: Cyber 2. Uses the as_admin fixture (Role.ADMIN) and, separately,
as_lecturer to confirm the role guard actually rejects the wrong role —
without that check these tests would pass even if require_roles(Role.ADMIN)
were silently dropped from the router.

An import saves to the courses, so every test that imports uses course codes
no real course has, and hands the courses it created to the db fixture's
cleanup.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy import select

from app.auth.store import ADMIN_ID
from app.models.course import Course
from app.models.course_enrollment import CourseEnrollment, CourseLecturer
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role

from .session_support import add_course, sign_in_as, track_courses

TIMETABLE_CSV = (
    b"course_code,lecturer,day,start_time,end_time,room\n"
    b"CSIT321,Dr. Orumchian,Monday,09:00,11:00,Room 12\n"
    b"CSIT101,Dr. Orumchian,Monday,10:00,12:00,Room 4\n"
)


def _code() -> str:
    """A course code no real course has, so the import creates a fresh one."""
    return f"ZT{uuid4().hex[:8].upper()}"


async def test_timetable_upload_reports_conflicts(db, app):
    client, factory, created = db
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    one, two = _code(), _code()
    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\n"
        + f"{one},Dr. Orumchian,Monday,09:00,11:00,Room 12\n".encode()
        + f"{two},Dr. Orumchian,Monday,10:00,12:00,Room 4\n".encode()
    )
    resp = client.post("/api/v1/admin/timetable", files={"file": ("t.csv", timetable, "text/csv")})
    await track_courses(factory, created, one, two)
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows_read"] == 2
    assert len(body["conflicts"]) == 1
    assert "Dr. Orumchian" in body["conflicts"][0]


def test_timetable_upload_rejects_bad_extension(as_admin):
    files = {"file": ("timetable.pdf", b"not a csv", "application/pdf")}
    resp = as_admin.post("/api/v1/admin/timetable", files=files)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_roster_upload_parses_rows(db, app):
    client, factory, created = db
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    code = _code()
    roster = f"student_email,student_name,course_code\na.student@uni.test,A Student,{code}\n"
    resp = client.post("/api/v1/admin/roster", files={"file": ("r.csv", roster, "text/csv")})
    await track_courses(factory, created, code)
    assert resp.status_code == 200
    assert resp.json()["rows_read"] == 1


def test_admin_routes_reject_non_admin_role(as_lecturer):
    """A lecturer principal must not be able to import a timetable."""
    files = {"file": ("timetable.csv", TIMETABLE_CSV, "text/csv")}
    resp = as_lecturer.post("/api/v1/admin/timetable", files=files)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_routes_reject_unauthenticated(client):
    """No dependency override at all: the real get_principal stub should 401."""
    files = {"file": ("timetable.csv", TIMETABLE_CSV, "text/csv")}
    resp = client.post("/api/v1/admin/timetable", files=files)
    assert resp.status_code == 401


async def test_imports_are_matched_against_the_accounts_that_exist(db, app):
    """Lecturers are matched by name against real accounts, and students by
    email, so only the people without one are reported unmatched."""
    client, factory, created = db
    tag = uuid4().hex[:6]
    lecturer = f"Dr Known {tag}"
    async with factory() as seed:
        user = User(name=lecturer, role="lecturer", email=f"{uuid4().hex}@t.test")
        seed.add(user)
        await seed.flush()
        created["user"].append(user.user_id)
        await seed.commit()
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    one, two = _code(), _code()
    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\n"
        + f"{one},{lecturer},Monday,09:00,11:00,Room 12\n".encode()
        + f"{two},Nobody Here {tag},Tuesday,09:00,11:00,Room 4\n".encode()
    )
    roster = (
        b"student_email,student_name,course_code\n"
        + f"s{tag}@uni.test,Stranger Person {tag},{one}\n".encode()
    )
    lecturers = client.post(
        "/api/v1/admin/timetable", files={"file": ("t.csv", timetable, "text/csv")}
    ).json()
    students = client.post(
        "/api/v1/admin/roster", files={"file": ("r.csv", roster, "text/csv")}
    ).json()
    await track_courses(factory, created, one, two)

    assert lecturers["unmatched_lecturers"] == [f"Nobody Here {tag}"]
    assert students["unmatched_students"] == [f"Stranger Person {tag} (s{tag}@uni.test)"]


async def test_a_timetable_creates_its_courses_and_assigns_their_lecturers(db, app):
    client, factory, created = db
    tag = uuid4().hex[:6]
    async with factory() as seed:
        lecturer = User(name=f"Dr Timetable {tag}", role="lecturer", email=f"{uuid4().hex}@t.test")
        seed.add(lecturer)
        await seed.commit()
    created["user"].append(lecturer.user_id)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    one, two = _code(), _code()
    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\n"
        + f"{one.lower()},Dr Timetable {tag},Monday,09:00,11:00,Room 12\n".encode()
        + f"{one},Dr Timetable {tag},Wednesday,09:00,11:00,Room 12\n".encode()
        + f"{two},Dr Timetable {tag},Tuesday,09:00,11:00,Room 4\n".encode()
    )
    files = {"file": ("t.csv", timetable, "text/csv")}

    first = client.post("/api/v1/admin/timetable", files=files).json()
    again = client.post("/api/v1/admin/timetable", files=files).json()
    await track_courses(factory, created, one, two)

    assert first["courses_created"] == [one, two]
    assert first["lecturers_assigned"] == 2
    assert first["unmatched_lecturers"] == []
    assert again["courses_created"] == []
    assert again["lecturers_assigned"] == 0
    async with factory() as look:
        taught = set(
            await look.scalars(
                select(Course.code)
                .join(CourseLecturer, CourseLecturer.course_id == Course.id)
                .where(CourseLecturer.user_id == lecturer.user_id)
            )
        )
    assert taught == {one, two}


async def test_a_roster_puts_students_on_the_course_without_moving_them(db, app):
    client, factory, created = db
    home = (await add_course(factory, created)).id
    email = f"{uuid4().hex}@t.test"
    async with factory() as seed:
        user = User(name="Roster Student", role="student", email=email)
        seed.add(user)
        await seed.flush()
        student = Student(
            user_id=user.user_id,
            course_id=home,
            consent_status="granted",
            enrolled_at=date.today(),
        )
        seed.add(student)
        await seed.commit()
    created["user"].append(user.user_id)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    code = _code()
    stranger = f"nobody-{code.lower()}@uni.test"
    roster = (
        "student_email,student_name,course_code\n"
        f"{email.upper()},Roster Student,{code}\n"
        f"{stranger},No Account,{code}\n"
    )
    files = {"file": ("r.csv", roster, "text/csv")}

    first = client.post("/api/v1/admin/roster", files=files).json()
    again = client.post("/api/v1/admin/roster", files=files).json()
    await track_courses(factory, created, code)

    assert first["courses_created"] == [code]
    assert first["students_enrolled"] == 1
    assert first["unmatched_students"] == [f"No Account ({stranger})"]
    assert again["students_enrolled"] == 0
    async with factory() as look:
        course_id = await look.scalar(select(Course.id).where(Course.code == code))
        enrolled = await look.scalar(
            select(CourseEnrollment.course_id).where(
                CourseEnrollment.student_id == student.student_id,
                CourseEnrollment.course_id == course_id,
            )
        )
        still_home = await look.scalar(
            select(Student.course_id).where(Student.student_id == student.student_id)
        )
    assert enrolled == course_id
    assert still_home == home


async def test_a_bad_course_code_saves_nothing(db, app):
    client, factory, created = db
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    good = _code()
    roster = (
        "student_email,student_name,course_code\n"
        f"a@uni.test,A Student,{good}\n"
        "b@uni.test,B Student,CSIT 321\n"
    )
    resp = client.post("/api/v1/admin/roster", files={"file": ("r.csv", roster, "text/csv")})
    await track_courses(factory, created, good)

    assert resp.status_code == 422
    assert "CSIT 321" in resp.json()["error"]["message"]
    async with factory() as look:
        assert await look.scalar(select(Course.id).where(Course.code == good)) is None
