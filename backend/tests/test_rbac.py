"""Real-token RBAC checks across the Cyber 2 administrator routes."""

from fastapi.testclient import TestClient

from tests.dev_credentials import ADMIN_PASSWORD, LECTURER_PASSWORD, STUDENT_PASSWORD

TIMETABLE = (
    b"course_code,lecturer,day,start_time,end_time,room\n"
    b"CSIT321,Dr. Orumchian,Monday,09:00,11:00,Room 12\n"
)
ROSTER = (
    b"student_email,student_name,course_code\n"
    b"student@clip.example.com,Development Student,CSIT321\n"
)


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _accept_terms(client: TestClient, token: str) -> None:
    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={"consent_type": "terms", "granted": True},
    )
    assert response.status_code == 201


def test_admin_route_requires_terms_even_for_an_admin(client: TestClient) -> None:
    token = _login(client, "admin@clip.example.com", ADMIN_PASSWORD)
    response = client.post(
        "/api/v1/admin/timetable",
        headers=_headers(token),
        files={"file": ("timetable.csv", TIMETABLE, "text/csv")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_student_and_lecturer_cannot_upload_a_timetable(client: TestClient) -> None:
    for email, password in (
        ("student@clip.example.com", STUDENT_PASSWORD),
        ("lecturer@clip.example.com", LECTURER_PASSWORD),
    ):
        token = _login(client, email, password)
        _accept_terms(client, token)
        response = client.post(
            "/api/v1/admin/timetable",
            headers=_headers(token),
            files={"file": ("timetable.csv", TIMETABLE, "text/csv")},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_can_reach_timetable_and_roster_handlers(client: TestClient) -> None:
    token = _login(client, "admin@clip.example.com", ADMIN_PASSWORD)
    _accept_terms(client, token)

    timetable = client.post(
        "/api/v1/admin/timetable",
        headers=_headers(token),
        files={"file": ("timetable.csv", TIMETABLE, "text/csv")},
    )
    roster = client.post(
        "/api/v1/admin/roster",
        headers=_headers(token),
        files={"file": ("roster.csv", ROSTER, "text/csv")},
    )

    assert timetable.status_code == 200
    assert timetable.json()["rows_read"] == 1
    assert roster.status_code == 200
    assert roster.json()["rows_read"] == 1


def test_admin_routes_without_a_token_return_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/roster",
        files={"file": ("roster.csv", ROSTER, "text/csv")},
    )
    assert response.status_code == 401
