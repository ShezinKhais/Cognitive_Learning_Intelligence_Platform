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
    """Names are matched against real lecturer and student accounts, so only
    the people without one are reported unmatched."""
    from uuid import uuid4

    from app.auth.store import ADMIN_ID
    from app.models.user import User
    from app.schemas.identity import Role

    from .session_support import sign_in_as

    client, factory, created = db
    tag = uuid4().hex[:6]
    lecturer, student = f"Dr Known {tag}", f"Known Student {tag}"
    async with factory() as seed:
        for name, role in ((lecturer, "lecturer"), (student, "student")):
            user = User(name=name, role=role, email=f"{uuid4().hex}@t.test")
            seed.add(user)
            await seed.flush()
            created["user"].append(user.user_id)
        await seed.commit()
    sign_in_as(app, ADMIN_ID, Role.ADMIN)

    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\n"
        + f"CSIT321,{lecturer},Monday,09:00,11:00,Room 12\n".encode()
        + f"CSIT101,Nobody Here {tag},Tuesday,09:00,11:00,Room 4\n".encode()
    )
    roster = (
        b"student_email,student_name,course_code\n"
        + f"k@uni.test,{student},CSIT321\n".encode()
        + f"s@uni.test,Stranger Person {tag},CSIT321\n".encode()
    )
    lecturers = client.post(
        "/api/v1/admin/timetable", files={"file": ("t.csv", timetable, "text/csv")}
    ).json()
    students = client.post(
        "/api/v1/admin/roster", files={"file": ("r.csv", roster, "text/csv")}
    ).json()

    assert lecturers["unmatched_lecturers"] == [f"Nobody Here {tag}"]
    assert students["unmatched_students"] == [f"Stranger Person {tag}"]
