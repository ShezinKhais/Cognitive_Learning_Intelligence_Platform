"""Saving timetable and roster imports, against a real database."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import uuid4

from sqlalchemy import select

from app.auth.store import ADMIN_ID
from app.models.course import Course
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role
from app.services.import_persistence import LOCAL_TIME, next_occurrence

from .session_support import add_course, sign_in_as


def _timetable(code: str, lecturer: str = "Development Lecturer") -> bytes:
    return (
        "course_code,lecturer,day,start_time,end_time,room\n"
        f"{code},{lecturer},Monday,09:00,11:00,Room 12\n"
        f"{code},{lecturer},Wednesday,13:00,15:00,Room 4\n"
    ).encode()


def _upload(client, path: str, body: bytes):
    return client.post(f"/api/v1/admin/{path}", files={"file": (f"{path}.csv", body, "text/csv")})


async def _track_course(factory, created, code: str) -> None:
    async with factory() as check:
        course_id = (await check.execute(select(Course.id).where(Course.code == code))).scalar_one()
    created["course"].append(course_id)


def test_next_occurrence_is_the_coming_weekday_in_local_time() -> None:
    # Thursday 2026-10-15, 10:00 local (06:00 UTC).
    now = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)

    monday = next_occurrence("Monday", time(9, 0), now)
    later_today = next_occurrence("Thursday", time(13, 0), now)
    passed_today = next_occurrence("Thursday", time(9, 0), now)

    assert monday.astimezone(LOCAL_TIME).date() == date(2026, 10, 19)
    assert monday.astimezone(LOCAL_TIME).time() == time(9, 0)
    assert later_today.astimezone(LOCAL_TIME).date() == date(2026, 10, 15)
    assert passed_today.astimezone(LOCAL_TIME).date() == date(2026, 10, 22)


async def test_a_timetable_creates_courses_and_sessions_once(db, app) -> None:
    client, factory, created = db
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    code = f"I{uuid4().hex[:8]}"

    first = _upload(client, "timetable", _timetable(code))
    await _track_course(factory, created, code)
    again = _upload(client, "timetable", _timetable(code))

    assert first.status_code == 200
    assert first.json()["sessions_created"] == 2
    assert first.json()["unmatched_lecturers"] == []
    assert again.json()["sessions_created"] == 0
    async with factory() as check:
        rows = (
            (
                await check.execute(
                    select(SessionModel)
                    .join(Course, Course.id == SessionModel.course_id)
                    .where(Course.code == code)
                )
            )
            .scalars()
            .all()
        )
    assert {row.status for row in rows} == {"prepared"}
    assert all(row.end_time > row.start_time for row in rows)


async def test_a_timetable_with_a_clash_saves_nothing(db, app) -> None:
    client, factory, created = db
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    code = f"I{uuid4().hex[:8]}"
    body = (
        "course_code,lecturer,day,start_time,end_time,room\n"
        f"{code},Development Lecturer,Monday,09:00,11:00,Room 12\n"
        f"{code},Development Lecturer,Monday,10:00,12:00,Room 4\n"
    ).encode()

    response = _upload(client, "timetable", body).json()

    assert response["sessions_created"] == 0
    assert len(response["conflicts"]) == 1
    async with factory() as check:
        assert (await check.execute(select(Course).where(Course.code == code))).first() is None


async def test_an_unknown_lecturer_is_reported_and_skipped(db, app) -> None:
    client, factory, created = db
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    code = f"I{uuid4().hex[:8]}"

    response = _upload(client, "timetable", _timetable(code, "Dr. Nobody Atall")).json()

    assert response["sessions_created"] == 0
    assert response["unmatched_lecturers"] == ["Dr. Nobody Atall"]
    async with factory() as check:
        assert (await check.execute(select(Course).where(Course.code == code))).first() is None


async def test_a_roster_enrols_known_students_and_reports_the_rest(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    user_id = uuid4()
    email = f"{user_id.hex}@roster.test"
    async with factory() as seed:
        seed.add(User(user_id=user_id, name="Roster Student", role="student", email=email))
        await seed.commit()
    created["user"].append(user_id)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)
    body = (
        "student_email,student_name,course_code\n"
        f"{email.upper()},Roster Student,{course.code}\n"
        f"ghost@roster.test,Ghost Student,{course.code}\n"
        f"{email},Roster Student,NOSUCHCOURSE\n"
    ).encode()

    response = _upload(client, "roster", body).json()

    assert response["rows_read"] == 3
    assert response["unmatched_students"] == ["Ghost Student (ghost@roster.test)"]
    assert any("NOSUCHCOURSE" in problem for problem in response["conflicts"])
    async with factory() as check:
        enrolled = (
            await check.execute(select(Student).where(Student.user_id == user_id))
        ).scalar_one()
    assert enrolled.course_id == course.id


async def test_a_student_already_on_another_course_is_not_moved(db, app) -> None:
    client, factory, created = db
    home = await add_course(factory, created)
    other = await add_course(factory, created)
    user_id = uuid4()
    email = f"{user_id.hex}@roster.test"
    async with factory() as seed:
        seed.add(User(user_id=user_id, name="Settled Student", role="student", email=email))
        await seed.flush()
        seed.add(
            Student(
                user_id=user_id,
                course_id=home.id,
                consent_status="granted",
                enrolled_at=date(2026, 9, 1),
            )
        )
        await seed.commit()
    created["user"].append(user_id)
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    body = f"student_email,student_name,course_code\n{email},Settled Student,{other.code}\n"
    response = _upload(client, "roster", body.encode()).json()

    assert any("already enrolled" in problem for problem in response["conflicts"])
    async with factory() as check:
        kept = (
            await check.execute(select(Student.course_id).where(Student.user_id == user_id))
        ).scalar_one()
    assert kept == home.id
