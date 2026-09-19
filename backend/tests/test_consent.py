"""Consent remains granular, revocable and role-appropriate."""

from fastapi.testclient import TestClient

from .dev_credentials import (
    ADMIN_PASSWORD,
    LECTURER_PASSWORD,
    STUDENT_PASSWORD,
)


def _token(
    client: TestClient,
    email: str,
    password: str,
) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200

    return response.json()["access_token"]


def _student_token(
    client: TestClient,
) -> str:
    return _token(
        client,
        "student@clip.example.com",
        STUDENT_PASSWORD,
    )


def _admin_token(
    client: TestClient,
) -> str:
    return _token(
        client,
        "admin@clip.example.com",
        ADMIN_PASSWORD,
    )


def _lecturer_token(
    client: TestClient,
) -> str:
    return _token(
        client,
        "lecturer@clip.example.com",
        LECTURER_PASSWORD,
    )


def _headers(
    token: str,
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
    }


def _grant_terms(
    client: TestClient,
    token: str,
) -> None:
    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={
            "consent_type": "terms",
            "granted": True,
        },
    )

    assert response.status_code == 201


def test_consent_can_be_granted_and_appears_in_me(
    client: TestClient,
) -> None:
    token = _student_token(client)

    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={
            "consent_type": "camera",
            "granted": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["consent_type"] == "camera"
    assert response.json()["granted"] is True

    me = client.get(
        "/api/v1/auth/me",
        headers=_headers(token),
    )

    assert me.status_code == 200
    assert me.json()["consents"] == ["camera"]


def test_one_consent_can_be_revoked_without_changing_another(
    client: TestClient,
) -> None:
    token = _student_token(client)

    for consent_type in (
        "camera",
        "microphone",
    ):
        response = client.post(
            "/api/v1/auth/consent",
            headers=_headers(token),
            json={
                "consent_type": consent_type,
                "granted": True,
            },
        )

        assert response.status_code == 201

    revoked = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={
            "consent_type": "camera",
            "granted": False,
        },
    )

    assert revoked.status_code == 201
    assert revoked.json()["granted"] is False

    me = client.get(
        "/api/v1/auth/me",
        headers=_headers(token),
    )

    assert me.status_code == 200
    assert me.json()["consents"] == ["microphone"]


def test_admin_cannot_submit_student_monitoring_consent(
    client: TestClient,
) -> None:
    token = _admin_token(client)

    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={
            "consent_type": "camera",
            "granted": True,
        },
    )

    assert response.status_code == 403


def test_lecturer_cannot_submit_student_monitoring_consent(
    client: TestClient,
) -> None:
    token = _lecturer_token(client)

    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={
            "consent_type": "microphone",
            "granted": True,
        },
    )

    assert response.status_code == 403


def test_admin_can_record_terms_consent(
    client: TestClient,
) -> None:
    token = _admin_token(client)

    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={
            "consent_type": "terms",
            "granted": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["consent_type"] == "terms"
    assert response.json()["granted"] is True


def test_single_consent_requires_authentication(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/consent",
        json={
            "consent_type": "terms",
            "granted": True,
        },
    )

    assert response.status_code == 401


def test_me_remains_accessible_before_terms_consent(
    client: TestClient,
) -> None:
    token = _student_token(client)

    response = client.get(
        "/api/v1/auth/me",
        headers=_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["consents"] == []


def test_student_without_terms_is_blocked_from_protected_sessions(
    client: TestClient,
) -> None:
    token = _student_token(client)

    response = client.get(
        "/api/v1/sessions",
        headers=_headers(token),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert response.json()["error"]["detail"]["missing"] == ["terms"]


def test_student_with_terms_passes_the_consent_gate(
    client: TestClient,
) -> None:
    token = _student_token(client)

    _grant_terms(client, token)

    response = client.get(
        "/api/v1/sessions",
        headers=_headers(token),
    )

    # Reaching the handler at all (rather than CONSENT_REQUIRED) proves
    # Cyber 1's consent gate allowed the consented student through.
    assert response.status_code == 200


def test_admin_without_terms_is_blocked_from_admin_routes(
    client: TestClient,
) -> None:
    token = _admin_token(client)

    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\nCS101,Dr Test,Monday,09:00,10:00,A1\n"
    )

    response = client.post(
        "/api/v1/admin/timetable",
        headers=_headers(token),
        files={
            "file": (
                "timetable.csv",
                timetable,
                "text/csv",
            ),
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert response.json()["error"]["detail"]["missing"] == ["terms"]


def test_admin_with_terms_passes_the_consent_gate(
    client: TestClient,
) -> None:
    token = _admin_token(client)

    _grant_terms(client, token)

    timetable = (
        b"course_code,lecturer,day,start_time,end_time,room\nCS101,Dr Test,Monday,09:00,10:00,A1\n"
    )

    response = client.post(
        "/api/v1/admin/timetable",
        headers=_headers(token),
        files={
            "file": (
                "timetable.csv",
                timetable,
                "text/csv",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["rows_read"] == 1
