"""Consent remains granular, revocable and available before terms are accepted."""

from fastapi.testclient import TestClient

from tests.dev_credentials import STUDENT_PASSWORD


def _token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "student@clip.example.com", "password": STUDENT_PASSWORD},
    )
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_consent_can_be_granted_and_appears_in_me(client: TestClient) -> None:
    token = _token(client)
    response = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={"consent_type": "camera", "granted": True},
    )
    assert response.status_code == 201
    assert response.json()["consent_type"] == "camera"
    assert response.json()["granted"] is True

    me = client.get("/api/v1/auth/me", headers=_headers(token)).json()
    assert me["consents"] == ["camera"]


def test_one_consent_can_be_revoked_without_changing_another(client: TestClient) -> None:
    token = _token(client)
    for consent_type in ("camera", "microphone"):
        client.post(
            "/api/v1/auth/consent",
            headers=_headers(token),
            json={"consent_type": consent_type, "granted": True},
        )

    revoked = client.post(
        "/api/v1/auth/consent",
        headers=_headers(token),
        json={"consent_type": "camera", "granted": False},
    )
    assert revoked.status_code == 201
    assert revoked.json()["granted"] is False

    me = client.get("/api/v1/auth/me", headers=_headers(token)).json()
    assert me["consents"] == ["microphone"]


def test_consent_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/consent",
        json={"consent_type": "terms", "granted": True},
    )
    assert response.status_code == 401
