"""Application settings, loaded from environment (.env in development)."""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_KEY = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Application
    clip_env: str = "development"
    clip_secret_key: str = "change-me-in-production"
    clip_log_level: str = "INFO"

    # Database
    database_url: str = (
        "postgresql+asyncpg://clip:clip_dev_password@localhost:5432/clip"
    )

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

    # Uploads (Includes CSV and XLSX for admin timetable/roster imports)
    max_upload_bytes: int = 52_428_800
    allowed_upload_extensions: str = "pdf,pptx,docx,txt,csv,xlsx"

    # Retention (UAE PDPL)
    data_retention_days: int = 90

    @property
    def is_production(self) -> bool:
        return self.clip_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _reject_unsafe_production_config(self) -> "Settings":
        """Fail at startup rather than serving a class with a known-bad config.

        A default signing key means anyone can forge a token for any student.
        Discovering that during a demo is worse than refusing to boot.
        """
        if not self.is_production:
            return self

        problems = []
        if self.clip_secret_key == INSECURE_SECRET_KEY:
            problems.append("CLIP_SECRET_KEY is still the default")

        # Parse DATABASE_URL for thorough production checks
        parsed_db = urlparse(self.database_url)
        db_password = parsed_db.password or ""
        db_host = parsed_db.hostname or ""

        if not db_password or db_password in {"clip_dev_password", "postgres", "password", "admin", "root"}:
            problems.append("DATABASE_URL uses a missing, default, or weak password")
        if db_host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            problems.append("DATABASE_URL points to localhost in production")

        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self

    @property
    def teams_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.tenant_id)

    @property
    def upload_extensions(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.allowed_upload_extensions.split(",")
            if e.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()