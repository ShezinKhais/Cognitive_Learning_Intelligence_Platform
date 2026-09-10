"""Development identity stores and transient login-security state.

Development uses fixed in-memory identities so the application and tests can
run without a local PostgreSQL database.

Production identity and consent persistence must use the database repositories.
The functions below deliberately refuse to return development repositories in
production so a deployment cannot silently lose consent decisions after a
restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from app.core.config import Settings
from app.schemas.identity import ConsentType, Role

STUDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
LECTURER_ID = UUID("22222222-2222-2222-2222-222222222222")
ADMIN_ID = UUID("33333333-3333-3333-3333-333333333333")

# Prototype-only credentials.
# Only password hashes are stored here.
DEV_STUDENT_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$QcKKGcvq3iTHPqYPKj0ePw==$TY1Ln5kfviWL4GOQrqVgXcW0VttV_qKFKNqsQF_nHSA="
)

DEV_LECTURER_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$1Vnxp8VqRirlbn6ik6zhWA==$RDJFpsJRXtMQkSsKUDv6RD2a54_v-pXmnsto-uPiu70="
)

DEV_ADMIN_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$GcIiUKdjqP1oOIC-QSP_Ng==$1F7aKH4Yn895ka2991JZxbcGIO3zwmsQgYcWlsZwNdk="
)

MAX_FAILED_LOGIN_ATTEMPTS = 5
ACCOUNT_LOCK_DURATION = timedelta(minutes=15)


@dataclass(
    frozen=True,
    slots=True,
)
class UserRecord:
    id: UUID
    email: str
    full_name: str
    role: Role
    password_hash: str
    active: bool = True


@dataclass(
    frozen=True,
    slots=True,
)
class ConsentRecord:
    user_id: UUID
    consent_type: ConsentType
    granted: bool
    recorded_at: datetime


class LoginSecurityStore:
    """Track temporary failed-login and lockout state.

    Authentication identities themselves are persisted by BBIS/Nour's
    database layer in production. This object only tracks the short-lived
    security counters used by the Cyber 1 login flow.
    """

    def __init__(self) -> None:
        self._failed_attempts: dict[
            UUID,
            int,
        ] = {}

        self._locked_until: dict[
            UUID,
            datetime,
        ] = {}

        self._lock = RLock()

    def is_locked(
        self,
        user_id: UUID,
    ) -> bool:
        with self._lock:
            locked_until = self._locked_until.get(user_id)

            if locked_until is None:
                return False

            if datetime.now(UTC) >= locked_until:
                self._locked_until.pop(
                    user_id,
                    None,
                )
                self._failed_attempts.pop(
                    user_id,
                    None,
                )

                return False

            return True

    def record_failed_login(
        self,
        user_id: UUID,
    ) -> bool:
        """Increment failures and report whether locking began."""

        with self._lock:
            count = (
                self._failed_attempts.get(
                    user_id,
                    0,
                )
                + 1
            )

            self._failed_attempts[user_id] = count

            if count >= MAX_FAILED_LOGIN_ATTEMPTS:
                self._locked_until[user_id] = datetime.now(UTC) + ACCOUNT_LOCK_DURATION

                return True

            return False

    def reset_failed_logins(
        self,
        user_id: UUID,
    ) -> None:
        with self._lock:
            self._failed_attempts.pop(
                user_id,
                None,
            )

            self._locked_until.pop(
                user_id,
                None,
            )

    def reset(self) -> None:
        """Clear transient security state for tests."""

        with self._lock:
            self._failed_attempts.clear()
            self._locked_until.clear()


class InMemoryUserRepository:
    """Development-only fixed user repository."""

    def __init__(
        self,
        users: list[UserRecord],
    ) -> None:
        self._by_id = {user.id: user for user in users}

        self._by_email = {user.email.lower(): user for user in users}

    def get_by_email(
        self,
        email: str,
    ) -> UserRecord | None:
        return self._by_email.get(email.strip().lower())

    def get_by_id(
        self,
        user_id: UUID,
    ) -> UserRecord | None:
        return self._by_id.get(user_id)


class InMemoryConsentRepository:
    """Development-only granular consent repository."""

    def __init__(self) -> None:
        self._records: dict[
            tuple[
                UUID,
                ConsentType,
            ],
            ConsentRecord,
        ] = {}

        self._lock = RLock()

    def record(
        self,
        user_id: UUID,
        consent_type: ConsentType,
        granted: bool,
        *,
        recorded_at: datetime | None = None,
    ) -> ConsentRecord:
        record = ConsentRecord(
            user_id=user_id,
            consent_type=consent_type,
            granted=granted,
            recorded_at=(recorded_at or datetime.now(UTC)),
        )

        with self._lock:
            self._records[
                (
                    user_id,
                    consent_type,
                )
            ] = record

        return record

    def granted_for(
        self,
        user_id: UUID,
    ) -> set[ConsentType]:
        with self._lock:
            return {
                consent_type
                for (
                    record_user,
                    consent_type,
                ), record in (self._records.items())
                if (record_user == user_id and record.granted)
            }

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def _build_dev_users() -> list[UserRecord]:
    return [
        UserRecord(
            id=STUDENT_ID,
            email=("student@clip.example.com"),
            full_name=("Development Student"),
            role=Role.STUDENT,
            password_hash=(DEV_STUDENT_PASSWORD_HASH),
        ),
        UserRecord(
            id=LECTURER_ID,
            email=("lecturer@clip.example.com"),
            full_name=("Development Lecturer"),
            role=Role.LECTURER,
            password_hash=(DEV_LECTURER_PASSWORD_HASH),
        ),
        UserRecord(
            id=ADMIN_ID,
            email=("admin@clip.example.com"),
            full_name=("Development Administrator"),
            role=Role.ADMIN,
            password_hash=(DEV_ADMIN_PASSWORD_HASH),
        ),
    ]


_DEV_USERS = InMemoryUserRepository(_build_dev_users())

_DEV_CONSENTS = InMemoryConsentRepository()

_LOGIN_SECURITY = LoginSecurityStore()


def get_user_repository(
    settings: Settings,
) -> InMemoryUserRepository:
    """Return development users only.

    Production callers must use
    app.repositories.user_repository.UserRepository.
    """

    if settings.is_production:
        raise RuntimeError("Production users must use the database UserRepository.")

    return _DEV_USERS


def get_consent_repository(
    settings: Settings,
) -> InMemoryConsentRepository:
    """Return the development consent repository only.

    Production callers must use
    app.repositories.consent_repository.ConsentRepository.
    """

    if settings.is_production:
        raise RuntimeError("Production consent must use the database ConsentRepository.")

    return _DEV_CONSENTS


def get_login_security_store() -> LoginSecurityStore:
    """Return transient failed-login/lockout state."""

    return _LOGIN_SECURITY
