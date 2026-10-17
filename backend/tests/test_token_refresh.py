"""Refreshing an access token, so a long class does not end in a sign-in.

Owner: General CS, Phase 8, on Cyber 1's Phase 1 authentication. A token
lasts access_token_expire_minutes. The client swaps it for a fresh one before
it expires, using the refresh token in an httpOnly cookie, and the sign-in
still ends max_sign_in_hours after the password was typed.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.v1.identity import REFRESH_COOKIE, REFRESH_HEADER
from app.auth.store import STUDENT_ID, get_user_repository
from app.core.config import get_settings
from app.core.security import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.schemas.identity import Role

from .dev_credentials import LECTURER_PASSWORD

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


@pytest.fixture(autouse=True)
def empty_cookie_jar(client: TestClient):
    """The client is shared by the session, and so is its cookie jar."""
    client.cookies.clear()
    yield
    client.cookies.clear()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cookie(token: str, header: bool = True) -> dict[str, str]:
    headers = {"Cookie": f"{REFRESH_COOKIE}={token}"}
    if header:
        headers[REFRESH_HEADER] = "1"
    return headers


def _student(**kwargs):  # noqa: ANN003, ANN202
    settings = get_settings()
    user = get_user_repository(settings).get_by_id(STUDENT_ID)
    assert user is not None
    return settings, user, kwargs.pop("role", user.role)


def _student_token(**kwargs) -> str:  # noqa: ANN003
    settings, user, role = _student(**kwargs)
    token, _ = create_access_token(
        user_id=user.id, role=role, email=user.email, settings=settings, **kwargs
    )
    return token


def _student_refresh(auth_time: datetime | None = None, **kwargs) -> str:  # noqa: ANN003
    settings, user, role = _student(**kwargs)
    token, _ = create_refresh_token(
        user_id=user.id,
        role=role,
        email=user.email,
        settings=settings,
        auth_time=auth_time or datetime.now(UTC),
    )
    return token


def _sign_in(client: TestClient) -> tuple[dict, str]:
    response = client.post(
        LOGIN,
        json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD},
    )
    assert response.status_code == 200
    return response.json(), response.cookies[REFRESH_COOKIE]


def test_sign_in_sets_an_httponly_cookie_scoped_to_the_auth_routes(client: TestClient) -> None:
    response = client.post(
        LOGIN,
        json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD},
    )

    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{REFRESH_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    # The cookie never appears in the body, where a script could read it.
    assert response.cookies[REFRESH_COOKIE] not in response.text


def test_the_cookie_is_swapped_for_a_fresh_token_that_works(client: TestClient) -> None:
    _, cookie = _sign_in(client)
    client.cookies.clear()

    response = client.post(REFRESH, headers=_cookie(cookie))

    assert response.status_code == 200
    body = response.json()
    assert (body["token_type"], body["role"], body["expires_in"]) == ("bearer", "lecturer", 3600)
    me = client.get("/api/v1/auth/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "lecturer@clip.example.com"


def test_an_access_token_cannot_be_refreshed(client: TestClient) -> None:
    # One taken from the page ends at its own expiry, as a bearer or as a cookie.
    login, _ = _sign_in(client)
    client.cookies.clear()

    as_bearer = client.post(
        REFRESH, headers={**_bearer(login["access_token"]), REFRESH_HEADER: "1"}
    )
    as_cookie = client.post(REFRESH, headers=_cookie(login["access_token"]))

    assert (as_bearer.status_code, as_cookie.status_code) == (401, 401)


def test_a_refresh_token_is_not_an_access_token(client: TestClient) -> None:
    refresh_token = _student_refresh()

    with pytest.raises(TokenValidationError):
        decode_access_token(refresh_token, get_settings())
    assert client.get("/api/v1/auth/me", headers=_bearer(refresh_token)).status_code == 401


def test_refresh_without_the_header_is_refused(client: TestClient) -> None:
    # A page on another site can make the browser send the cookie, but not
    # add a custom header without a preflight.
    _, cookie = _sign_in(client)
    client.cookies.clear()

    assert client.post(REFRESH, headers=_cookie(cookie, header=False)).status_code == 401


def test_sign_out_clears_the_cookie(client: TestClient) -> None:
    _sign_in(client)

    response = client.post(LOGOUT, headers={REFRESH_HEADER: "1"})

    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f'{REFRESH_COOKIE}="";') or set_cookie.startswith(
        f"{REFRESH_COOKIE}=;"
    )
    assert "Max-Age=0" in set_cookie
    assert client.post(REFRESH, headers={REFRESH_HEADER: "1"}).status_code == 401


def test_sign_out_without_the_header_is_refused(client: TestClient) -> None:
    assert client.post(LOGOUT).status_code == 401


def test_the_refresh_token_keeps_the_original_sign_in_time() -> None:
    signed_in = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)

    claims = decode_refresh_token(_student_refresh(signed_in), get_settings())

    assert claims.auth_time == signed_in


def test_refreshing_carries_the_sign_in_time_forward(client: TestClient) -> None:
    signed_in = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)

    renewed = client.post(REFRESH, headers=_cookie(_student_refresh(signed_in)))

    assert renewed.status_code == 200
    claims = decode_access_token(renewed.json()["access_token"], get_settings())
    assert claims.auth_time == signed_in


def test_near_the_cap_the_new_token_ends_when_the_sign_in_does(client: TestClient) -> None:
    signed_in = datetime.now(UTC) - timedelta(hours=11, minutes=30)

    renewed = client.post(REFRESH, headers=_cookie(_student_refresh(signed_in)))

    assert renewed.status_code == 200
    assert 1700 <= renewed.json()["expires_in"] <= 1800


def test_no_refresh_token_outlives_its_sign_in() -> None:
    signed_in = datetime.now(UTC) - timedelta(hours=12, seconds=1)

    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(
            _student_refresh(signed_in), get_settings().clip_secret_key, algorithms=["HS256"]
        )


def test_no_access_token_outlives_its_sign_in() -> None:
    signed_in = datetime.now(UTC) - timedelta(hours=12, seconds=1)
    token = _student_token(auth_time=signed_in)

    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, get_settings().clip_secret_key, algorithms=["HS256"])


def test_past_the_cap_the_user_signs_in_again(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    # Even a refresh token still inside its own lifetime, as one issued before
    # the cap was lowered would be, is not honoured once the sign-in is too old.
    token = _student_refresh(datetime.now(UTC) - timedelta(hours=6))
    monkeypatch.setattr(get_settings(), "max_sign_in_hours", 5)

    response = client.post(REFRESH, headers=_cookie(token))

    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {REFRESH_HEADER: "1"},
        {REFRESH_HEADER: "1", "Cookie": f"{REFRESH_COOKIE}=not-a-jwt"},
    ],
    ids=["missing", "malformed"],
)
def test_a_missing_or_malformed_cookie_is_refused(client: TestClient, headers) -> None:  # noqa: ANN001
    assert client.post(REFRESH, headers=headers).status_code == 401


def test_a_forged_refresh_token_is_refused(client: TestClient) -> None:
    claims = jwt.decode(_student_refresh(), get_settings().clip_secret_key, algorithms=["HS256"])
    forged = jwt.encode(claims, "someone-elses-key-at-least-32-bytes", algorithm="HS256")

    assert client.post(REFRESH, headers=_cookie(forged)).status_code == 401


def test_a_refresh_token_for_a_role_the_user_no_longer_has_is_refused(client: TestClient) -> None:
    token = _student_refresh(role=Role.ADMIN)

    assert client.post(REFRESH, headers=_cookie(token)).status_code == 401


def test_a_disabled_account_cannot_refresh(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    token = _student_refresh()
    repository = get_user_repository(get_settings())
    user = repository.get_by_id(STUDENT_ID)
    assert user is not None
    disabled = dataclasses.replace(user, active=False)
    monkeypatch.setattr(
        repository, "get_by_id", lambda user_id: disabled if user_id == STUDENT_ID else None
    )

    assert client.post(REFRESH, headers=_cookie(token)).status_code == 401


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
