"""Application settings, loaded from environment (.env in development)."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import unquote, urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_KEY = "change-me-in-production-use-32-plus-bytes"
DEV_DATABASE_PASSWORD = "clip_dev_password"

MIN_SECRET_KEY_LENGTH = 32
MIN_DATABASE_PASSWORD_LENGTH = 12

WEAK_DATABASE_PASSWORDS = frozenset(
    {
        "admin",
        "changeme",
        "change-me",
        "clip",
        "dev",
        "letmein",
        "password",
        "passw0rd",
        "postgres",
        "root",
        "secret",
        "test",
        "123456",
    }
)


def database_password_problem(
    url: str,
) -> str | None:
    """Describe an unsafe database password, or return None."""
    try:
        raw = urlsplit(url).password
    except ValueError:
        return "DATABASE_URL could not be parsed"

    if not raw:
        return "DATABASE_URL carries no password"

    password = unquote(raw)

    if password == DEV_DATABASE_PASSWORD:
        return "DATABASE_URL still uses the development password"

    if password.lower() in WEAK_DATABASE_PASSWORDS:
        return "DATABASE_URL uses a well-known password"

    if len(password) < MIN_DATABASE_PASSWORD_LENGTH:
        return (
            f"the DATABASE_URL password is shorter than {MIN_DATABASE_PASSWORD_LENGTH} characters"
        )

    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    clip_env: str = "development"
    clip_secret_key: str = INSECURE_SECRET_KEY
    clip_log_level: str = "INFO"
    access_token_expire_minutes: int = 60

    # Database
    database_url: str = f"postgresql+asyncpg://clip:{DEV_DATABASE_PASSWORD}@localhost:5432/clip"

    # LLM
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # Written by `teams app create --env .env`
    client_id: str = ""
    client_secret: str = ""
    tenant_id: str = ""

    # Session behaviour
    checkpoint_interval_seconds: int = 1200
    checkpoint_response_window_seconds: int = 30
    comprehension_alert_threshold: float = 0.50
    comprehension_alert_min_respondents: int = 5
    dynamic_prompt_max_per_student: int = 3

    # Uploads
    max_upload_bytes: int = 52_428_800
    allowed_upload_extensions: str = "pdf,pptx,docx,txt"

    # Retention (UAE PDPL)
    data_retention_days: int = 90

    @property
    def is_production(self) -> bool:
        return self.clip_env.lower() in {
            "production",
            "prod",
        }

    @model_validator(mode="after")
    def _reject_unsafe_production_config(
        self,
    ) -> Settings:
        """Refuse to start production with unsafe secrets."""
        if not self.is_production:
            return self

        problems: list[str] = []

        if self.clip_secret_key == INSECURE_SECRET_KEY:
            problems.append("CLIP_SECRET_KEY is still the default")
        elif len(self.clip_secret_key) < MIN_SECRET_KEY_LENGTH:
            problems.append(f"CLIP_SECRET_KEY is shorter than {MIN_SECRET_KEY_LENGTH} characters")

        database_problem = database_password_problem(self.database_url)

        if database_problem:
            problems.append(database_problem)

        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))

        return self

    @property
    def teams_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.tenant_id)

    @property
    def upload_extensions(self) -> set[str]:
        return {
            extension.strip().lower()
            for extension in (self.allowed_upload_extensions.split(","))
            if extension.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
