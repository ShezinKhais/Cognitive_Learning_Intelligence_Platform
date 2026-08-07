"""Cyber 1 authentication and current-user tests."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.auth.store import (
    ADMIN_ID,
    STUDENT_ID,
    get_user_repository,
)
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.identity import Role
from tests.dev_credentials import ADMIN_PASSWORD, LECTURER_PASSWORD, STUDENT_PASSWORD


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_student_login_returns_a_bearer_token(client: TestClient) -> None:
    response = _login(client, "student@clip.example.com", STUDENT_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "student"
    assert body["expires_in"] == 3600
    assert body["access_token"]


def test_lecturer_login_returns_the_lecturer_role(client: TestClient) -> None:
    response = _login(client, "lecturer@clip.example.com", LECTURER_PASSWORD)
    assert response.status_code == 200
    assert response.json()["role"] == "lecturer"


def test_admin_login_returns_the_admin_role(client: TestClient) -> None:
    response = _login(client, "admin@clip.example.com", ADMIN_PASSWORD)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_wrong_password_and_unknown_email_use_the_same_public_error(client: TestClient) -> None:
    wrong = _login(client, "student@clip.example.com", "wrong-password")
    unknown = _login(client, "nobody@clip.example.com", "wrong-password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_five_wrong_passwords_lock_the_development_account(client: TestClient) -> None:
    for _ in range(5):
        response = _login(client, "student@clip.example.com", "wrong-password")
        assert response.status_code == 401

    still_blocked = _login(client, "student@clip.example.com", STUDENT_PASSWORD)
    assert still_blocked.status_code == 401


def test_missing_invalid_and_malformed_tokens_return_401(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers=_bearer("not-a-jwt")).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_expired_token_returns_401(client: TestClient) -> None:
    settings = get_settings()
    user = get_user_repository(settings).get_by_id(STUDENT_ID)
    assert user is not None
    token, _ = create_access_token(
        user_id=user.id,
        role=user.role,
        email=user.email,
        settings=settings,
        expires_delta=timedelta(seconds=-1),
    )
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_me_returns_the_authenticated_user(client: TestClient) -> None:
    token = _login(client, "admin@clip.example.com", ADMIN_PASSWORD).json()["access_token"]
    response = client.get("/api/v1/auth/me", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {
        "id": str(ADMIN_ID),
        "email": "admin@clip.example.com",
        "full_name": "Development Administrator",
        "role": "admin",
        "consents": [],
    }


def test_token_claim_role_must_match_the_current_user(client: TestClient) -> None:
    settings = get_settings()
    user = get_user_repository(settings).get_by_id(STUDENT_ID)
    assert user is not None
    token, _ = create_access_token(
        user_id=user.id,
        role=Role.ADMIN,
        email=user.email,
        settings=settings,
    )
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401
