"""Temporary in-memory identity and consent repositories.

BBIS can replace these classes with PostgreSQL implementations later without
changing the route contracts, JWT format or role guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from app.core.config import Settings
from app.schemas.identity import ConsentType, Role

STUDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
LECTURER_ID = UUID("22222222-2222-2222-2222-222222222222")
ADMIN_ID = UUID("33333333-3333-3333-3333-333333333333")

# Prototype-only credentials. The repository stores only their hashes and is
# disabled completely in production. These are documented so the team can test.
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


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: UUID
    email: str
    full_name: str
    role: Role
    password_hash: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    user_id: UUID
    consent_type: ConsentType
    granted: bool
    recorded_at: datetime


class InMemoryUserRepository:
    def __init__(self, users: list[UserRecord]) -> None:
        self._by_id = {user.id: user for user in users}
        self._by_email = {user.email.lower(): user for user in users}
        self._failed_attempts: dict[UUID, int] = {}
        self._locked: set[UUID] = set()
        self._lock = RLock()

    def get_by_email(self, email: str) -> UserRecord | None:
        return self._by_email.get(email.strip().lower())

    def get_by_id(self, user_id: UUID) -> UserRecord | None:
        return self._by_id.get(user_id)

    def is_locked(self, user_id: UUID) -> bool:
        with self._lock:
            return user_id in self._locked

    def record_failed_login(self, user_id: UUID) -> bool:
        """Increment failures and return True when the account becomes locked."""
        with self._lock:
            count = self._failed_attempts.get(user_id, 0) + 1
            self._failed_attempts[user_id] = count
            if count >= MAX_FAILED_LOGIN_ATTEMPTS:
                self._locked.add(user_id)
                return True
            return False

    def reset_failed_logins(self, user_id: UUID) -> None:
        with self._lock:
            self._failed_attempts.pop(user_id, None)
            self._locked.discard(user_id)

    def reset_security_state(self) -> None:
        """Test helper; production persistence will move this state to PostgreSQL."""
        with self._lock:
            self._failed_attempts.clear()
            self._locked.clear()


class InMemoryConsentRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[UUID, ConsentType], ConsentRecord] = {}
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
            recorded_at=recorded_at or datetime.now(UTC),
        )
        with self._lock:
            self._records[(user_id, consent_type)] = record
        return record

    def granted_for(self, user_id: UUID) -> set[ConsentType]:
        with self._lock:
            return {
                consent_type
                for (record_user, consent_type), record in self._records.items()
                if record_user == user_id and record.granted
            }

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def _build_dev_users() -> list[UserRecord]:
    return [
        UserRecord(
            id=STUDENT_ID,
            email="student@clip.example.com",
            full_name="Development Student",
            role=Role.STUDENT,
            password_hash=DEV_STUDENT_PASSWORD_HASH,
        ),
        UserRecord(
            id=LECTURER_ID,
            email="lecturer@clip.example.com",
            full_name="Development Lecturer",
            role=Role.LECTURER,
            password_hash=DEV_LECTURER_PASSWORD_HASH,
        ),
        UserRecord(
            id=ADMIN_ID,
            email="admin@clip.example.com",
            full_name="Development Administrator",
            role=Role.ADMIN,
            password_hash=DEV_ADMIN_PASSWORD_HASH,
        ),
    ]


_DEV_USERS = InMemoryUserRepository(_build_dev_users())
_EMPTY_USERS = InMemoryUserRepository([])
_CONSENTS = InMemoryConsentRepository()


def get_user_repository(settings: Settings) -> InMemoryUserRepository:
    """Development identities are unavailable when the app is in production."""
    return _EMPTY_USERS if settings.is_production else _DEV_USERS


def get_consent_repository() -> InMemoryConsentRepository:
    return _CONSENTS
