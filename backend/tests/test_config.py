"""Configuration safety.

Development defaults are convenient and unsafe. These pin the boundary between
the two so nobody ships the convenient version.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import INSECURE_SECRET_KEY, Settings
from app.core.logging import RequestIdFilter, request_id_var


def test_development_tolerates_defaults() -> None:
    settings = Settings(clip_env="development")
    assert settings.clip_secret_key == INSECURE_SECRET_KEY
    assert not settings.is_production


def test_production_rejects_the_default_secret_key() -> None:
    with pytest.raises(ValueError, match="CLIP_SECRET_KEY"):
        Settings(clip_env="production", database_url="postgresql+asyncpg://u:p@h/db")


def test_production_rejects_the_development_database_password() -> None:
    with pytest.raises(ValueError, match="development password"):
        Settings(
            clip_env="production",
            clip_secret_key="a-real-key",
            database_url="postgresql+asyncpg://clip:clip_dev_password@localhost:5432/clip",
        )


def test_production_starts_when_configured_properly() -> None:
    settings = Settings(
        clip_env="production",
        clip_secret_key="a-real-key",
        database_url="postgresql+asyncpg://clip:s3cret@db:5432/clip",
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
