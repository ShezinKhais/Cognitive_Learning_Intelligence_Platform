"""Integration tests for the administrator console routes.

Owner: Cyber 2. Uses the as_admin fixture (Role.ADMIN) and, separately,
as_lecturer to confirm the role guard actually rejects the wrong role —
without that check these tests would pass even if require_roles(Role.ADMIN)
were silently dropped from the router.
"""

from __future__ import annotations

TIMETABLE_CSV = (
    b"course_code,lecturer,day,start_time,end_time,room\n"
    b"CSIT321,Dr. Orumchian,Monday,09:00,11:00,Room 12\n"
    b"CSIT101,Dr. Orumchian,Monday,10:00,12:00,Room 4\n"
)

ROSTER_CSV = b"student_email,student_name,course_code\na.student@uni.test,A Student,CSIT321\n"


def test_timetable_upload_reports_conflicts(as_admin):
    files = {"file": ("timetable.csv", TIMETABLE_CSV, "text/csv")}
    resp = as_admin.post("/api/v1/admin/timetable", files=files)
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


def test_roster_upload_parses_rows(as_admin):
    files = {"file": ("roster.csv", ROSTER_CSV, "text/csv")}
    resp = as_admin.post("/api/v1/admin/roster", files=files)
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
    """Timetables match lecturer names; rosters match active student emails."""
    from uuid import uuid4

    from app.auth.store import ADMIN_ID
    from app.models.user import User
    from app.schemas.identity import Role

    from .session_support import add_course, enrol, sign_in_as

    client, factory, created = db
    tag = uuid4().hex[:6]
    lecturer, student = f"Dr Known {tag}", f"Known Student {tag}"
    home = await add_course(factory, created)
    email = f"{tag}@t.test"
    async with factory() as seed:
        for name, role in ((lecturer, "lecturer"), (student, "student")):
            user = User(
                name=name, role=role, email=email if role == "student" else f"{uuid4().hex}@t.test"
            )
            seed.add(user)
            await seed.flush()
            created["user"].append(user.user_id)
        await seed.commit()
    await enrol(factory, home, user_id=user.user_id)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\n"
        + f"CSIT321,{lecturer},Monday,09:00,11:00,Room 12\n".encode()
        + f"CSIT101,Nobody Here {tag},Tuesday,09:00,11:00,Room 4\n".encode()
    )
    roster = (
        b"student_email,student_name,course_code\n"
        + f"{email},{student},CSIT321\n".encode()
        + f"s@uni.test,Stranger Person {tag},CSIT321\n".encode()
    )
    lecturers = client.post(
        "/api/v1/admin/timetable", files={"file": ("t.csv", timetable, "text/csv")}
    ).json()
    students = client.post(
        "/api/v1/admin/roster", files={"file": ("r.csv", roster, "text/csv")}
    ).json()

    assert lecturers["unmatched_lecturers"] == [f"Nobody Here {tag}"]
    assert students["unmatched_students"] == ["s@uni.test"]


async def test_confirmed_imports_persist_dated_sessions_and_additional_courses(db, app):
    from datetime import UTC, datetime
    from uuid import uuid4

    from sqlalchemy import select

    from app.auth.store import ADMIN_ID
    from app.models.course import Course
    from app.models.course_enrollment import CourseEnrollment, CourseLecturer
    from app.models.session import Session
    from app.models.student import Student
    from app.models.user import User
    from app.schemas.identity import Role

    from .session_support import add_course, enrol, sign_in_as

    client, factory, created = db
    home = await add_course(factory, created)
    tag = uuid4().hex[:8]
    code = f"NEW{tag.upper()}"
    lecturer_name = f"Lecturer {tag}"
    student_email = f"s-{tag}@uni.test"
    async with factory() as seed:
        lecturer = User(email=f"l-{tag}@uni.test", name=lecturer_name, role="lecturer")
        student = User(email=student_email, name="Test Student", role="student")
        seed.add_all((lecturer, student))
        await seed.commit()
    created["user"].extend((lecturer.user_id, student.user_id))
    await enrol(factory, home, user_id=student.user_id)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    timetable_row = f"{code.lower()},{lecturer_name},Monday,09:00,11:00,Room 12\n".encode()
    timetable = TIMETABLE_CSV.splitlines(keepends=True)[0] + timetable_row * 2
    timetable_url = "/api/v1/admin/timetable"
    timetable_file = {"file": ("t.csv", timetable, "text/csv")}
    week = {"week_start": "2026-11-09"}
    response = client.post(timetable_url, files=timetable_file, data=week)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["sessions_created"] == 0
    assert preview["sessions_to_create"] == 1
    assert preview["memberships_changed"] == preview["courses_changed"] == 1
    assert "Duplicate" in preview["rows"][1]["detail"]
    async with factory() as read:
        assert await read.scalar(select(Course.id).where(Course.code == code)) is None

    confirmation = {**week, "preview_token": preview["preview_token"]}
    wrong_week = client.post(
        timetable_url, files=timetable_file, data={**confirmation, "week_start": "2026-11-16"}
    )
    assert wrong_week.status_code == 409
    response = client.post(timetable_url, files=timetable_file, data=confirmation)
    assert response.status_code == 200, response.text
    async with factory() as read:
        course_id = await read.scalar(select(Course.id).where(Course.code == code))
        assert course_id is not None
        created["course"].append(course_id)
        session = (await read.scalars(select(Session).where(Session.course_id == course_id))).one()
        session_id = session.session_id
        assert session.status == "prepared"
        assert session.instructor_id == lecturer.user_id
        assert session.start_time == datetime(2026, 11, 9, 5, tzinfo=UTC)
        assert session.end_time == datetime(2026, 11, 9, 7, tzinfo=UTC)
        assert await read.get(CourseLecturer, (course_id, lecturer.user_id)) is not None
    assert response.json()["sessions_created"] == 1
    assert client.post(timetable_url, files=timetable_file, data=confirmation).status_code == 409
    duplicate = client.post(timetable_url, files=timetable_file, data=week).json()
    assert duplicate["sessions_to_create"] == 0

    overlap_row = timetable_row.replace(b"09:00,11:00", b"10:00,12:00")
    overlap_file = {"file": ("t.csv", timetable.splitlines(keepends=True)[0] + overlap_row)}
    overlap = client.post(timetable_url, files=overlap_file, data=week).json()
    assert overlap["conflicts"]
    assert overlap["preview_token"] is None

    roster = (
        b"student_email,student_name,course_code\n"
        + f"{student_email},Test Student,{code}\n".encode() * 2
        + f"unknown@uni.test,Test Student,{code}\n".encode()
    )
    roster_file = {"file": ("r.csv", roster, "text/csv")}
    roster_url = "/api/v1/admin/roster"
    roster_preview = client.post(roster_url, files=roster_file).json()
    assert roster_preview["memberships_changed"] == 1
    assert roster_preview["unmatched_students"] == ["unknown@uni.test"]
    sign_in_as(app, student.user_id, Role.STUDENT)
    session_url = f"/api/v1/sessions/{session_id}"
    assert client.get(session_url).status_code == 404

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    applied = client.post(
        roster_url, files=roster_file, data={"preview_token": roster_preview["preview_token"]}
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["memberships_changed"] == 1
    assert client.post(roster_url, files=roster_file).json()["memberships_changed"] == 0
    async with factory() as read:
        profile = await read.scalar(select(Student).where(Student.user_id == student.user_id))
        assert profile.course_id == home.id
        assert await read.get(CourseEnrollment, (profile.student_id, course_id)) is not None

    sign_in_as(app, student.user_id, Role.STUDENT)
    assert client.get(session_url).status_code == 200
    sign_in_as(app, lecturer.user_id, Role.LECTURER)
    assert client.get(session_url).status_code == 200


async def test_timetable_reuses_cancelled_slot_and_respects_actual_end_time(db, app):
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.auth.store import ADMIN_ID
    from app.models.session import Session
    from app.models.user import User
    from app.schemas.identity import Role

    from .session_support import add_course, sign_in_as

    client, factory, created = db
    course = await add_course(factory, created)
    tag = uuid4().hex[:8]
    name = f"Lecturer {tag}"
    async with factory() as seed:
        lecturer = User(email=f"{tag}@uni.test", name=name, role="lecturer")
        seed.add(lecturer)
        await seed.flush()
        created["user"].append(lecturer.user_id)
        seed.add(
            Session(
                course_id=course.id,
                instructor_id=lecturer.user_id,
                start_time=datetime(2026, 11, 9, 5, tzinfo=UTC),
                end_time=datetime(2026, 11, 9, 7, tzinfo=UTC),
                status="cancelled",
                mode="in_person",
            )
        )
        await seed.commit()

    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    csv = f"{course.code},{name},Monday,09:00,11:00,Room 12\n".encode()
    files = {"file": ("t.csv", TIMETABLE_CSV.splitlines(keepends=True)[0] + csv)}
    url = "/api/v1/admin/timetable"
    week = {"week_start": "2026-11-09"}
    preview = client.post(url, files=files, data=week)
    assert preview.status_code == 200, preview.text
    assert preview.json()["sessions_to_create"] == 1

    async with factory() as seed:
        seed.add(
            Session(
                course_id=course.id,
                instructor_id=lecturer.user_id,
                start_time=datetime(2026, 11, 8, 19, tzinfo=UTC),
                ended_at=datetime(2026, 11, 9, 5, 30, tzinfo=UTC),
                status="ended",
                mode="in_person",
            )
        )
        await seed.commit()

    confirm = client.post(
        url, files=files, data={**week, "preview_token": preview.json()["preview_token"]}
    )
    assert confirm.status_code == 409
    blocked = client.post(url, files=files, data=week).json()
    assert blocked["conflicts"]
    assert blocked["preview_token"] is None
