"""Application settings, loaded from environment (.env in development)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    clip_env: str = "development"
    clip_secret_key: str = "change-me-in-production"
    clip_log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://clip:clip_dev_password@localhost:5432/clip"

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
    def teams_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.tenant_id)

    @property
    def upload_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_upload_extensions.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
