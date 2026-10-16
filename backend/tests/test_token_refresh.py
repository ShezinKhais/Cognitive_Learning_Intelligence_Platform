"""Refreshing an access token, so a long class does not end in a sign-in.

Owner: General CS, Phase 8, on Cyber 1's Phase 1 authentication. A token
lasts access_token_expire_minutes. The client swaps it for a fresh one before
it expires, and the sign-in still ends max_sign_in_hours after the password
was typed.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.store import STUDENT_ID, get_user_repository
from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.schemas.identity import Role

from .dev_credentials import LECTURER_PASSWORD

REFRESH = "/api/v1/auth/refresh"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _student_token(**kwargs) -> str:  # noqa: ANN003
    settings = get_settings()
    user = get_user_repository(settings).get_by_id(STUDENT_ID)
    assert user is not None
    token, _ = create_access_token(
        user_id=user.id,
        role=kwargs.pop("role", user.role),
        email=user.email,
        settings=settings,
        **kwargs,
    )
    return token


def test_a_valid_token_is_swapped_for_a_fresh_one_that_works(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD},
    ).json()

    response = client.post(REFRESH, headers=_bearer(login["access_token"]))

    assert response.status_code == 200
    body = response.json()
    assert (body["token_type"], body["role"], body["expires_in"]) == ("bearer", "lecturer", 3600)
    me = client.get("/api/v1/auth/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "lecturer@clip.example.com"


def test_the_refreshed_token_keeps_the_original_sign_in_time() -> None:
    signed_in = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    token = _student_token(auth_time=signed_in)

    assert decode_access_token(token, get_settings()).auth_time == signed_in


def test_refreshing_carries_the_sign_in_time_forward(client: TestClient) -> None:
    signed_in = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)

    renewed = client.post(REFRESH, headers=_bearer(_student_token(auth_time=signed_in)))

    assert renewed.status_code == 200
    claims = decode_access_token(renewed.json()["access_token"], get_settings())
    assert claims.auth_time == signed_in


def test_near_the_cap_the_new_token_ends_when_the_sign_in_does(client: TestClient) -> None:
    signed_in = datetime.now(UTC) - timedelta(hours=11, minutes=30)

    renewed = client.post(REFRESH, headers=_bearer(_student_token(auth_time=signed_in)))

    assert renewed.status_code == 200
    assert 1700 <= renewed.json()["expires_in"] <= 1800


def test_no_token_outlives_its_sign_in() -> None:
    signed_in = datetime.now(UTC) - timedelta(hours=12, seconds=1)
    token = _student_token(auth_time=signed_in)

    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, get_settings().clip_secret_key, algorithms=["HS256"])


def test_past_the_cap_the_user_signs_in_again(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    # Even a token still inside its own lifetime, as one issued before the cap
    # was lowered would be, is not renewed once the sign-in is too old.
    token = _student_token(auth_time=datetime.now(UTC) - timedelta(hours=6))
    monkeypatch.setattr(get_settings(), "max_sign_in_hours", 5)

    response = client.post(REFRESH, headers=_bearer(token))

    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        _bearer("not-a-jwt"),
    ],
    ids=["missing", "not-bearer", "malformed"],
)
def test_a_missing_or_malformed_token_is_refused(client: TestClient, headers) -> None:  # noqa: ANN001
    assert client.post(REFRESH, headers=headers).status_code == 401


def test_an_expired_token_cannot_be_refreshed(client: TestClient) -> None:
    token = _student_token(expires_delta=timedelta(seconds=-1))

    assert client.post(REFRESH, headers=_bearer(token)).status_code == 401


def test_a_forged_token_is_refused(client: TestClient) -> None:
    claims = jwt.decode(_student_token(), get_settings().clip_secret_key, algorithms=["HS256"])
    forged = jwt.encode(claims, "someone-elses-key-at-least-32-bytes", algorithm="HS256")

    assert client.post(REFRESH, headers=_bearer(forged)).status_code == 401


def test_a_token_for_a_role_the_user_no_longer_has_is_refused(client: TestClient) -> None:
    token = _student_token(role=Role.ADMIN)

    assert client.post(REFRESH, headers=_bearer(token)).status_code == 401


def test_a_disabled_account_cannot_refresh(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    token = _student_token()
    repository = get_user_repository(get_settings())
    user = repository.get_by_id(STUDENT_ID)
    assert user is not None
    disabled = dataclasses.replace(user, active=False)
    monkeypatch.setattr(
        repository, "get_by_id", lambda user_id: disabled if user_id == STUDENT_ID else None
    )

    assert client.post(REFRESH, headers=_bearer(token)).status_code == 401


def test_a_token_from_before_auth_time_began_its_sign_in_when_issued() -> None:
    settings = get_settings()
    issued = datetime.now(UTC).replace(microsecond=0)
    old = jwt.encode(
        {
            "sub": str(STUDENT_ID),
            "role": "student",
            "email": "student@clip.example.com",
            "iat": issued,
            "exp": issued + timedelta(minutes=5),
        },
        settings.clip_secret_key,
        algorithm="HS256",
    )

    assert decode_access_token(old, settings).auth_time == issued


@pytest.mark.parametrize("hours", [0, -1])
def test_a_sign_in_cap_below_an_hour_is_refused_at_startup(hours: int) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_sign_in_hours=hours)
