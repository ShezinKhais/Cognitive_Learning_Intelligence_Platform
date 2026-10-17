"""Failed sign-ins counted per address, beside the per-account lockout."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from app.api.v1.identity import REFRESH_COOKIE, _set_refresh_cookie
from app.auth.address_limiter import (
    MAX_TRACKED_ADDRESSES,
    LoginAddressLimiter,
    get_login_address_limiter,
)
from app.core.config import get_settings
from app.core.errors import RateLimitedError

from .dev_credentials import LECTURER_PASSWORD, STUDENT_PASSWORD

LOGIN = "/api/v1/auth/login"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_an_address_is_refused_once_it_has_failed_too_often() -> None:
    clock = Clock()
    limiter = LoginAddressLimiter(3, 600, clock)
    for _ in range(3):
        limiter.check("203.0.113.9")
        limiter.record_failure("203.0.113.9")

    with pytest.raises(RateLimitedError) as refused:
        limiter.check("203.0.113.9")

    assert refused.value.detail["retry_after_seconds"] == 600
    # Another address is unaffected.
    limiter.check("198.51.100.4")


def test_failures_age_out_of_the_window() -> None:
    clock = Clock()
    limiter = LoginAddressLimiter(2, 600, clock)
    limiter.record_failure("203.0.113.9")
    clock.now += 300
    limiter.record_failure("203.0.113.9")

    clock.now += 301
    limiter.check("203.0.113.9")

    with pytest.raises(RateLimitedError) as refused:
        limiter.record_failure("203.0.113.9")
        limiter.check("203.0.113.9")
    assert refused.value.detail["retry_after_seconds"] == 299


def test_the_table_is_bounded() -> None:
    limiter = LoginAddressLimiter(5, 600, Clock())
    for index in range(MAX_TRACKED_ADDRESSES + 50):
        limiter.record_failure(f"10.{index // 65536}.{index // 256 % 256}.{index % 256}")

    assert len(limiter._failures) == MAX_TRACKED_ADDRESSES


def test_the_route_answers_429_before_checking_the_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "login_failures_per_address", 3)
    get_login_address_limiter.cache_clear()
    try:
        # One wrong password on each of several accounts: the spray the
        # per-account lockout never sees.
        for email in (
            "student@clip.example.com",
            "lecturer@clip.example.com",
            "x@clip.example.com",
        ):
            response = client.post(LOGIN, json={"email": email, "password": "wrong-password"})
            assert response.status_code == 401

        refused = client.post(
            LOGIN, json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD}
        )

        assert refused.status_code == 429
        assert refused.json()["error"]["code"] == "RATE_LIMITED"
        assert REFRESH_COOKIE not in refused.cookies
    finally:
        get_login_address_limiter.cache_clear()


def test_a_successful_sign_in_is_not_counted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "login_failures_per_address", 2)
    get_login_address_limiter.cache_clear()
    try:
        for _ in range(4):
            response = client.post(
                LOGIN, json={"email": "student@clip.example.com", "password": STUDENT_PASSWORD}
            )
            assert response.status_code == 200
    finally:
        get_login_address_limiter.cache_clear()
        client.cookies.clear()


def test_production_sends_the_cookie_to_a_teams_iframe_only_over_https() -> None:
    response = Response()

    _set_refresh_cookie(response, "token", 60, SimpleNamespace(is_production=True))

    set_cookie = response.headers["set-cookie"]
    for attribute in ("HttpOnly", "Secure", "Partitioned", "Path=/api/v1/auth", "Max-Age=60"):
        assert attribute in set_cookie
    assert "samesite=none" in set_cookie.lower()
