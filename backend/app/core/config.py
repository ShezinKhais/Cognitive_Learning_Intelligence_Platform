"""Application settings, loaded from environment (.env in development)."""

import logging
from functools import lru_cache
from urllib.parse import unquote, urlparse, urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_KEY = "change-me-in-production"

# The environments the application knows. Anything else is refused at startup:
# an unrecognised name ("Production " with a stray space, "prod-eu", "staging")
# used to count as development, which opens the interactive docs, CORS for the
# dev server and the well-known development accounts on a deployed host.
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})
KNOWN_ENVIRONMENTS = PRODUCTION_ENVIRONMENTS | {"development", "dev", "local", "test", "testing"}
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
    # A refresh renews the token, never the sign-in: after this long the user
    # signs in again, so refreshing cannot keep a stolen token alive past it.
    # A token that has been refreshed still works until its own expiry, as a
    # token does after sign-out: tokens are not revoked.
    max_sign_in_hours: int = Field(default=12, ge=1)

    # Failed sign-ins from one address before that address is refused for a
    # while. The per-account lockout stops guessing one password; this stops
    # one address trying a password across many accounts, or locking out a
    # whole class on purpose. A campus puts a class behind one address, so
    # it counts failures only and is set well above a room's typos.
    login_failures_per_address: int = Field(default=30, ge=1)
    login_failure_window_minutes: int = Field(default=10, ge=1)

    # Database
    database_url: str = f"postgresql+asyncpg://clip:{DEV_DATABASE_PASSWORD}@localhost:5432/clip"
    # Connections kept open, and how many more a busy moment may borrow. Every
    # request holds one for its length, so size + overflow is the most
    # requests the API serves at once; the rest wait up to the timeout.
    # Recycled before Postgres or a proxy between drops an idle connection.
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1)

    # LLM
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    # Tried once when the model above cannot answer. Empty for none. A smaller
    # model that answers is worth more to a waiting student than a better one
    # that does not.
    ollama_fallback_model: str = ""

    # Model calls. The model serves a few requests at a time however many are
    # sent, so more than that only makes every one of them slower. Two is
    # right for a laptop running Ollama; a host with a GPU raises it.
    ai_max_concurrency: int = Field(default=2, ge=1)
    # Calls allowed to wait for a slot. One more is refused at once.
    ai_queue_limit: int = Field(default=32, ge=0)
    # How long a call may wait for a slot before it is told to try again.
    ai_queue_timeout_seconds: float = Field(default=20.0, gt=0)
    # One attempt at a whole reply.
    ai_request_timeout_seconds: float = Field(default=60.0, gt=0)
    # A streamed reply: its first word, the gap between words, and all of it.
    # The first word waits longest, since it may include loading the model.
    ai_first_token_timeout_seconds: float = Field(default=30.0, gt=0)
    ai_stream_idle_timeout_seconds: float = Field(default=15.0, gt=0)
    ai_stream_timeout_seconds: float = Field(default=120.0, gt=0)
    # Attempts at the configured model, the first included.
    ai_max_attempts: int = Field(default=3, ge=1)
    # The pause before the second attempt. It doubles for each one after.
    ai_retry_pause_seconds: float = Field(default=0.5, ge=0)
    # Failures in a row before the model is left alone, and for how long.
    ai_breaker_failures: int = Field(default=5, ge=1)
    ai_breaker_cooldown_seconds: float = Field(default=30.0, gt=0)
    # Loading the model at startup, in the background. Loading a large model
    # from disk takes far longer than answering once it is loaded.
    ai_warmup_enabled: bool = True
    ai_warmup_timeout_seconds: float = Field(default=120.0, gt=0)
    # Ollama unloads a model five minutes after its last request unless
    # OLLAMA_KEEP_ALIVE says otherwise. A model idle for this long is asked
    # for one word, which resets that. Keep it below the server's limit; 0
    # leaves the model to unload.
    ai_keep_warm_seconds: float = Field(default=240.0, ge=0)

    # The tutor. How many questions one student may ask it in a minute. The
    # model serves a few requests at a time, so without this one student
    # sending question after question would hold the queue against the class.
    chat_questions_per_minute: int = Field(default=6, ge=1)
    # How many excerpts of the lecture material are put to the model with a
    # question. More gives it more to draw on and a longer prompt to read.
    chat_retrieved_chunks: int = Field(default=5, ge=1, le=20)

    # Short-answer questions alongside the multiple choice ones, one for every
    # three. Off until the question table stores reference answers and key
    # points: one saved without them has nothing to be marked against.
    free_text_questions_enabled: bool = False
    # Draft questions asked for per upload. The grounding checks reject any
    # whose answer is not in the lecturer's text, so fewer are kept than this.
    questions_per_material: int = Field(default=15, ge=1, le=30)
    # A second model call per multiple choice question that passes the
    # grounding checks, rejecting one whose cited slide makes another option
    # right too or contradicts the answer (generation.verify_draft).
    question_verification_enabled: bool = True

    # Describing the pictures in uploaded material with a local vision model,
    # so diagrams can be searched and asked about. Off by default: on a laptop
    # without a GPU each image takes seconds, and CI has no model at all.
    image_captioning_enabled: bool = False
    image_caption_model: str = "qwen2.5vl:3b"
    # One image's caption, the whole of it. A slow image is left uncaptioned.
    # Generous, because the first image of an upload also waits for the vision
    # model to load: measured at 55 seconds on an M-series Mac.
    image_caption_timeout_seconds: float = Field(default=120.0, gt=0)
    # Images captioned per material, in reading order. A deck rarely has more
    # diagrams worth describing, and the rest keep their placeholder.
    image_caption_max_images: int = Field(default=40, ge=0)
    # LibreOffice, for charts in WMF or EMF (often pasted from R or Excel),
    # which can only be described once converted. Empty finds it on the PATH
    # or in /Applications; without it those images are reported, not described.
    libreoffice_path: str = ""
    # OCR for scanned PDF pages, with Tesseract when it is installed (see
    # app/services/ocr.py). Empty finds it on the PATH or in /opt/homebrew;
    # without it scanned pages are skipped with a warning. The language is a
    # Tesseract language code, such as "eng" or "eng+ara".
    ocr_enabled: bool = True
    tesseract_path: str = ""
    ocr_language: str = "eng"

    # Written by `teams app create --env .env`
    client_id: str = ""
    client_secret: str = ""
    tenant_id: str = ""
    teams_notifications_enabled: bool = False
    teams_app_base_url: str = ""
    teams_app_id: str = ""

    # Session behaviour. Once a question closes, the next is due after a fresh
    # random wait between these two, so the class cannot predict it. Both 0
    # turns the automatic question cycle off, so questions go out only when
    # the lecturer sends one.
    checkpoint_interval_min_seconds: int = Field(default=900, ge=0)
    checkpoint_interval_max_seconds: int = Field(default=1200, ge=0)
    # The fixed interval these replaced. Still read so an .env that sets it
    # is told it no longer does anything, rather than ignored in silence.
    checkpoint_interval_seconds: int | None = None
    checkpoint_response_window_seconds: int = Field(default=30, ge=1)
    comprehension_alert_threshold: float = 0.50
    comprehension_alert_min_respondents: int = 5
    dynamic_prompt_max_per_student: int = Field(default=3, ge=0)
    # How long a private attention prompt stays on a student's screen.
    attention_prompt_ttl_seconds: int = Field(default=60, ge=1)
    # A student shown this many questions in a row without answering any is
    # sent a private prompt. 0 leaves prompting to engagement scoring alone.
    attention_prompt_after_missed_questions: int = Field(default=2, ge=0)

    # Attention signals from a student's device. One is expected every five
    # seconds; a socket may send one this often, after a short burst, before
    # its frames are dropped unread.
    attention_signal_min_interval_seconds: float = Field(default=2.0, ge=0)
    # How often a running session looks at its signals and breakout rooms.
    signal_watch_seconds: float = Field(default=10.0, gt=0)
    # Signals may prompt a student only once this much of the last two minutes
    # is covered by them, so nobody is judged on the first few seconds after
    # turning a camera on. 0 turns prompting from signals off.
    refocus_min_signal_seconds: float = Field(default=45.0, ge=0)
    # The least time between two prompts sent to one student on the strength
    # of their signals alone.
    refocus_cooldown_seconds: float = Field(default=300.0, ge=0)

    # Breakout rooms. How long one voice reading describes a member, how long
    # a room may be silent before it is quiet and before the lecturer is told
    # it needs attention, and how many rooms one session may have.
    room_voice_fresh_seconds: float = Field(default=20.0, gt=0)
    room_quiet_after_seconds: float = Field(default=60.0, gt=0)
    room_needs_attention_after_seconds: float = Field(default=180.0, gt=0)
    max_rooms_per_session: int = Field(default=50, ge=1)

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
    max_concurrent_material_jobs: int = Field(default=2, ge=1)

    # Cyber 1: compressed Office archive security limits.
    max_material_archive_entries: int = 4096
    max_material_uncompressed_bytes: int = 209_715_200  # 200 MiB

    # Cyber 1: post-extraction processing security limits.
    max_material_pages: int = 1000
    max_extracted_characters: int = 2_000_000
    max_material_chunks: int = 5000

    # Retention (UAE PDPL)
    data_retention_days: int = Field(default=90, ge=1)
    # How often the purge of data past that period runs, and how long one run
    # may take. A run cut short carries on at the next.
    retention_purge_interval_hours: float = Field(default=24.0, gt=0)
    retention_purge_timeout_minutes: float = Field(default=30.0, gt=0)

    @field_validator("clip_env")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        """Normalised, and refused if it names no environment we know."""
        name = value.strip().lower()
        if name not in KNOWN_ENVIRONMENTS:
            raise ValueError(
                f"CLIP_ENV {value!r} is not one of {', '.join(sorted(KNOWN_ENVIRONMENTS))}. "
                "An unrecognised name is refused rather than treated as development."
            )
        return name

    @property
    def is_production(self) -> bool:
        return self.clip_env in PRODUCTION_ENVIRONMENTS

    @model_validator(mode="after")
    def _check_room_timing(self) -> "Settings":
        """A room is quiet before it needs attention. With the two limits the
        other way round no room could ever be reported as quiet."""
        if self.room_needs_attention_after_seconds <= self.room_quiet_after_seconds:
            raise ValueError(
                "ROOM_NEEDS_ATTENTION_AFTER_SECONDS must be greater than ROOM_QUIET_AFTER_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def _check_teams_notifications(self) -> "Settings":
        if self.teams_notifications_enabled:
            if not self.teams_configured:
                raise ValueError(
                    "Teams notifications require CLIENT_ID, CLIENT_SECRET and TENANT_ID"
                )
            from uuid import UUID

            try:
                UUID(self.teams_app_id)
            except ValueError as exc:
                raise ValueError("TEAMS_APP_ID must be the Teams app's id, a UUID") from exc
            target = urlparse(self.teams_app_base_url)
            if (
                target.scheme != "https"
                or not target.hostname
                or target.username
                or target.password
                or target.query
                or target.fragment
                or target.path not in ("", "/")
            ):
                raise ValueError("TEAMS_APP_BASE_URL must be a public HTTPS origin")
        return self

    @model_validator(mode="after")
    def _check_question_timing(self) -> "Settings":
        """The random wait between questions must be a range that can be drawn
        from: both 0 for manual delivery only, or both above 0 with the minimum
        no greater than the maximum."""
        if self.checkpoint_interval_seconds is not None:
            logging.getLogger("clip.config").warning(
                "CHECKPOINT_INTERVAL_SECONDS is no longer read. The wait between "
                "questions is now random: set CHECKPOINT_INTERVAL_MIN_SECONDS and "
                "CHECKPOINT_INTERVAL_MAX_SECONDS (default 900 to 1200)."
            )
        low = self.checkpoint_interval_min_seconds
        high = self.checkpoint_interval_max_seconds
        if (low == 0) != (high == 0) or low > high:
            raise ValueError(
                "CHECKPOINT_INTERVAL_MIN_SECONDS and CHECKPOINT_INTERVAL_MAX_SECONDS must "
                "both be 0 (manual delivery only), or both above 0 with the minimum no "
                "greater than the maximum"
            )
        return self

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
