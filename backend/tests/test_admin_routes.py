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
