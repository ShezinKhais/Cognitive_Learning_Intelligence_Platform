"""Application settings, loaded from environment (.env in development)."""

from functools import lru_cache
from urllib.parse import unquote, urlparse, urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_KEY = "change-me-in-production"
DEV_DATABASE_PASSWORD = "clip_dev_password"

# A signing key is only as strong as its entropy. Thirty-two characters is the
# floor for HS256 and is short enough that nobody has an excuse.
MIN_SECRET_KEY_LENGTH = 32
MIN_DATABASE_PASSWORD_LENGTH = 12

# Not a complete list and not meant to be. These are the passwords a hurried
# deploy actually reaches for: the ones in this repo, in the compose file, and
# on the first page of every Postgres tutorial.
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


def database_password_problem(url: str) -> str | None:
    """Describe what is wrong with the password in a database URL, or None.

    The check this replaces looked for the literal development password, which
    meant `postgres` or `admin` sailed through. Look at the password itself
    instead of at one known string.
    """
    try:
        raw = urlsplit(url).password
    except ValueError:
        # An unparseable URL is not a password problem, but it is not something
        # to wave through in production either.
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
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    clip_env: str = "development"
    clip_secret_key: str = "change-me-in-production"
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

    # Uploads (Includes CSV and XLSX for admin timetable/roster imports)
    max_upload_bytes: int = 52_428_800
    allowed_upload_extensions: str = "pdf,pptx,docx,txt,csv,xlsx"
    # Uploads are processed after the request returns, so the bytes are written
    # here rather than held in memory until a worker reaches them. Relative to
    # the backend working directory in development; a deployment points this at
    # a mounted volume, or swaps LocalDiskStorage for a blob backend.
    upload_storage_dir: str = "var/uploads"
    # Extraction holds a CPU for fifteen to eighteen seconds per document, so
    # more parsers than cores means every lecturer waits longer than they would
    # have queued. Two is right for a laptop; a deployed host raises it.
    max_concurrent_material_jobs: int = 2

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
        elif len(self.clip_secret_key) < MIN_SECRET_KEY_LENGTH:
            problems.append(f"CLIP_SECRET_KEY is shorter than {MIN_SECRET_KEY_LENGTH} characters")

        parsed_db = urlparse(self.database_url)
        db_host = parsed_db.hostname or ""

        if db_host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            problems.append("DATABASE_URL points to localhost in production")

        database = database_password_problem(self.database_url)
        if database:
            problems.append(database)

        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self

    @property
    def teams_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.tenant_id)

    @property
    def upload_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_upload_extensions.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
