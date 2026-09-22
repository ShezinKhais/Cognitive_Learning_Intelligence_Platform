"""Configuration safety.

Development defaults are convenient and unsafe. These tests pin the boundary
between the two so nobody ships the convenient version.
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
    settings = Settings(
        clip_env="development",
    )

    assert settings.clip_secret_key == INSECURE_SECRET_KEY
    assert not settings.is_production


def test_production_rejects_default_secret_key() -> None:
    with pytest.raises(
        ValueError,
        match="CLIP_SECRET_KEY is still the default",
    ):
        Settings(
            clip_env="production",
            database_url=STRONG_DB,
        )


def test_production_rejects_a_short_secret_key() -> None:
    """A non-default key can still be too short to be safe."""
    with pytest.raises(
        ValueError,
        match=f"shorter than {MIN_SECRET_KEY_LENGTH}",
    ):
        Settings(
            clip_env="production",
            clip_secret_key=("k" * (MIN_SECRET_KEY_LENGTH - 1)),
            database_url=STRONG_DB,
        )


def test_production_rejects_the_development_database_password() -> None:
    with pytest.raises(
        ValueError,
        match="development password",
    ):
        Settings(
            clip_env="production",
            clip_secret_key=STRONG_KEY,
            database_url=("postgresql+asyncpg://clip:clip_dev_password@localhost:5432/clip"),
        )


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        (
            "postgres",
            "well-known password",
        ),
        (
            "Password",
            "well-known password",
        ),
        (
            "admin",
            "well-known password",
        ),
        (
            "changeme",
            "well-known password",
        ),
        (
            "hunter2",
            (f"shorter than {MIN_DATABASE_PASSWORD_LENGTH}"),
        ),
    ],
)
def test_production_rejects_any_weak_database_password(
    password: str,
    expected: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=expected,
    ):
        Settings(
            clip_env="production",
            clip_secret_key=STRONG_KEY,
            database_url=(f"postgresql+asyncpg://clip:{password}@db:5432/clip"),
        )


def test_production_rejects_a_database_url_with_no_password() -> None:
    with pytest.raises(
        ValueError,
        match="no password",
    ):
        Settings(
            clip_env="production",
            clip_secret_key=STRONG_KEY,
            database_url=("postgresql+asyncpg://clip@db:5432/clip"),
        )


def test_a_percent_encoded_weak_password_is_still_weak() -> None:
    problem = database_password_problem("postgresql+asyncpg://clip:change%2Dme@db/clip")

    assert problem is not None
    assert "well-known password" in problem


def test_development_is_left_alone_whatever_the_password() -> None:
    settings = Settings(
        clip_env="development",
        database_url=("postgresql+asyncpg://clip:x@db/clip"),
    )

    assert not settings.is_production


def test_production_starts_when_configured_properly() -> None:
    settings = Settings(
        clip_env="production",
        clip_secret_key=STRONG_KEY,
        database_url=STRONG_DB,
    )

    assert settings.is_production


def test_request_id_filter_adds_current_request_id() -> None:
    record = logging.LogRecord(
        "clip",
        logging.INFO,
        __file__,
        1,
        "msg",
        None,
        None,
    )

    token = request_id_var.set("trace-me")

    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    assert record.request_id == "trace-me"


def test_request_id_does_not_leak_between_requests(
    client: TestClient,
) -> None:
    first = client.get(
        "/api/v1/health",
        headers={
            "X-Request-ID": "one",
        },
    )

    second = client.get(
        "/api/v1/health",
    )

    assert first.headers["X-Request-ID"] == "one"
    assert second.headers["X-Request-ID"] != "one"


@pytest.mark.parametrize(
    ("low", "high"),
    [(900, 0), (0, 1200), (1300, 1200), (-1, 1200)],
)
def test_a_question_interval_range_that_cannot_be_drawn_from_is_refused(
    low: int, high: int
) -> None:
    with pytest.raises(ValueError, match="(?i)checkpoint_interval|greater than"):
        Settings(checkpoint_interval_min_seconds=low, checkpoint_interval_max_seconds=high)


def test_the_default_wait_between_questions_is_15_to_20_minutes() -> None:
    settings = Settings()

    assert (settings.checkpoint_interval_min_seconds, settings.checkpoint_interval_max_seconds) == (
        900,
        1200,
    )


def test_an_interval_of_zero_means_manual_delivery_only() -> None:
    settings = Settings(checkpoint_interval_min_seconds=0, checkpoint_interval_max_seconds=0)

    assert settings.checkpoint_interval_max_seconds == 0


def test_a_fixed_wait_is_a_range_of_one_value() -> None:
    settings = Settings(checkpoint_interval_min_seconds=600, checkpoint_interval_max_seconds=600)

    assert settings.checkpoint_interval_min_seconds == 600


def test_the_old_fixed_interval_setting_is_reported_not_silently_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="clip.config"):
        Settings(checkpoint_interval_seconds=1200)

    assert "CHECKPOINT_INTERVAL_SECONDS is no longer read" in caplog.text
