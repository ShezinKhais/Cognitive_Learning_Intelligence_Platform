"""Configuration safety.

Development defaults are convenient and unsafe. These pin the boundary between
the two so nobody ships the convenient version.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import (
    INSECURE_SECRET_KEY,
    MIN_DATABASE_PASSWORD_LENGTH,
    MIN_SECRET_KEY_LENGTH,
    Settings,
    database_password_problem,
)
from app.core.logging import RequestIdFilter, request_id_var

STRONG_KEY = "k" * MIN_SECRET_KEY_LENGTH
STRONG_DB = "postgresql+asyncpg://clip:Xq7-tunnel-marmot-93@db:5432/clip"


def test_development_tolerates_defaults() -> None:
    settings = Settings(clip_env="development")
    assert settings.clip_secret_key == INSECURE_SECRET_KEY
    assert not settings.is_production


def test_production_rejects_the_default_secret_key() -> None:
    with pytest.raises(ValueError, match="CLIP_SECRET_KEY"):
        Settings(clip_env="production", database_url=STRONG_DB)


def test_production_rejects_a_short_secret_key() -> None:
    """A key that is merely not the default is not a key. A short one is
    guessable offline from a single token."""
    with pytest.raises(ValueError, match=f"shorter than {MIN_SECRET_KEY_LENGTH}"):
        Settings(
            clip_env="production",
            clip_secret_key="k" * (MIN_SECRET_KEY_LENGTH - 1),
            database_url=STRONG_DB,
        )


def test_production_rejects_the_development_database_password() -> None:
    with pytest.raises(ValueError, match="missing, default, or weak password"):
        Settings(
            clip_env="production",
            clip_secret_key=STRONG_KEY,
            database_url="postgresql+asyncpg://clip:clip_dev_password@localhost:5432/clip",
        )


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("postgres", "well-known password"),
        ("Password", "well-known password"),  # matched case-insensitively
        ("admin", "well-known password"),
        ("changeme", "well-known password"),
        ("hunter2", f"shorter than {MIN_DATABASE_PASSWORD_LENGTH}"),
    ],
)
def test_production_rejects_any_weak_database_password(password: str, expected: str) -> None:
    """The check this replaces looked for one literal string, so every password
    on this list reached production untouched."""
    with pytest.raises(ValueError, match=expected):
        Settings(
            clip_env="production",
            clip_secret_key=STRONG_KEY,
            database_url=f"postgresql+asyncpg://clip:{password}@db:5432/clip",
        )


def test_production_rejects_a_database_url_with_no_password() -> None:
    with pytest.raises(ValueError, match="no password"):
        Settings(
            clip_env="production",
            clip_secret_key=STRONG_KEY,
            database_url="postgresql+asyncpg://clip@db:5432/clip",
        )


def test_a_percent_encoded_weak_password_is_still_weak() -> None:
    """Special characters have to be encoded in a URL, so the raw field is not
    the password. Decoding first is what makes the comparison meaningful."""
    assert database_password_problem("postgresql+asyncpg://clip:change%2Dme@db/clip")


def test_development_is_left_alone_whatever_the_password() -> None:
    """These checks exist to stop a bad production deploy, not to make local
    work annoying. Everyone on the team runs the compose password."""
    settings = Settings(clip_env="development", database_url="postgresql+asyncpg://clip:x@db/clip")
    assert not settings.is_production


def test_production_starts_when_configured_properly() -> None:
    settings = Settings(
        clip_env="production",
        clip_secret_key=STRONG_KEY,
        database_url=STRONG_DB,
    )
    assert settings.is_production


def test_log_records_carry_the_request_id() -> None:
    """Without this, an ID in an error body cannot be found in the logs."""
    record = logging.LogRecord("clip", logging.INFO, __file__, 1, "msg", None, None)

    token = request_id_var.set("trace-me")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    assert record.request_id == "trace-me"


def test_request_id_does_not_leak_between_requests(client: TestClient) -> None:
    first = client.get("/api/v1/health", headers={"X-Request-ID": "one"})
    second = client.get("/api/v1/health")

    assert first.headers["X-Request-ID"] == "one"
    assert second.headers["X-Request-ID"] != "one"
