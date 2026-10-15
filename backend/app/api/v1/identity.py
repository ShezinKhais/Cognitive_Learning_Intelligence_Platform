"""Authentication, consent and administration routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  Cyber 1: authentication, consent
  Cyber 2: administrator console
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, UploadFile, status
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    require_consents,
    require_roles,
)
from app.auth.login_security import PersistentLoginSecurityStore
from app.auth.service import granted_consents
from app.auth.store import (
    get_consent_repository,
    get_login_security_store,
    get_user_repository,
)
from app.core.audit import audit_action
from app.core.config import get_settings
from app.core.errors import (
    AuthenticationError,
    PermissionError_,
    ValidationError,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    verify_password,
)
from app.models.user import User
from app.realtime.classroom import classroom
from app.repositories.consent_repository import ConsentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.identity import (
    ConsentOut,
    ConsentRequest,
    ConsentType,
    LoginRequest,
    Role,
    TimetableImportResult,
    TokenResponse,
    UserOut,
)
from app.services.timetable_import import (
    detect_timetable_conflicts,
    match_names,
    parse_roster,
    parse_timetable,
)

log = logging.getLogger("clip.security")

GENERIC_LOGIN_ERROR = "Incorrect email or password."

router = APIRouter()

auth = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

admin = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[
        Depends(require_roles(Role.ADMIN)),
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


def _normalise_role(
    role: str | Role,
) -> Role:
    """Return a Role enum for either persisted or development users."""

    if isinstance(role, Role):
        return role

    return Role(role)


async def _read_upload_with_limit(
    file: UploadFile,
) -> bytes:
    """Read an upload without buffering more than the configured limit."""

    max_bytes = get_settings().max_upload_bytes

    if file.size is not None and file.size > max_bytes:
        raise ValidationError(
            "File exceeds the maximum upload size.",
            {
                "max_bytes": max_bytes,
                "reported_size": file.size,
            },
        )

    raw = await file.read(max_bytes + 1)

    if len(raw) > max_bytes:
        raise ValidationError(
            "File exceeds the maximum upload size.",
            {
                "max_bytes": max_bytes,
            },
        )

    return raw


@auth.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    payload: LoginRequest,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> TokenResponse:
    """Authenticate a user and return a bearer token.

    Development uses the fixed Cyber 1 development identities.
    Production resolves users through Nour's persisted User table.
    """

    email = str(payload.email).strip().lower()

    if settings.is_production:
        repository = UserRepository(db)

        user = await repository.get_by_email(email)
    else:
        repository = get_user_repository(settings)

        user = repository.get_by_email(email)

    # Always perform PBKDF2 verification, even when the email does not exist,
    # so registered accounts cannot be identified through timing differences.
    password_hash = (
        user.password_hash if (user is not None and user.password_hash) else DUMMY_PASSWORD_HASH
    )

    password_valid = verify_password(
        payload.password,
        password_hash,
    )

    if user is None:
        log.warning("security_event=LOGIN_FAILED reason=invalid_credentials")

        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    ip_address = request.client.host if request.client is not None else "unknown"

    if settings.is_production:
        security = PersistentLoginSecurityStore(db)

        if await security.is_locked(user.id):
            log.warning(
                "security_event=LOGIN_FAILED user_id=%s reason=account_locked",
                user.id,
            )

            raise AuthenticationError(GENERIC_LOGIN_ERROR)

        if not password_valid:
            locked = await security.record_failed_login(
                user.id,
                ip_address,
            )

            log.warning(
                "security_event=%s user_id=%s reason=invalid_credentials",
                ("ACCOUNT_LOCKED" if locked else "LOGIN_FAILED"),
                user.id,
            )

            raise AuthenticationError(GENERIC_LOGIN_ERROR)
    else:
        security = get_login_security_store()

        if security.is_locked(user.id):
            log.warning(
                "security_event=LOGIN_FAILED user_id=%s reason=account_locked",
                user.id,
            )

            raise AuthenticationError(GENERIC_LOGIN_ERROR)

        if not password_valid:
            locked = security.record_failed_login(user.id)

            log.warning(
                "security_event=%s user_id=%s reason=invalid_credentials",
                ("ACCOUNT_LOCKED" if locked else "LOGIN_FAILED"),
                user.id,
            )

            raise AuthenticationError(GENERIC_LOGIN_ERROR)

    if not user.active:
        log.warning(
            "security_event=LOGIN_FAILED user_id=%s reason=inactive",
            user.id,
        )

        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    role = _normalise_role(user.role)

    token, expires_in = create_access_token(
        user_id=user.id,
        role=role,
        email=user.email,
        settings=settings,
    )

    if settings.is_production:
        await security.record_successful_login(
            user.id,
            ip_address,
        )
    else:
        security.reset_failed_logins(user.id)

    log.info(
        "security_event=LOGIN_SUCCEEDED user_id=%s role=%s",
        user.id,
        role.value,
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=role,
    )


@auth.get(
    "/me",
    response_model=UserOut,
)
async def me(
    principal: CurrentUser,
    settings: AppSettings,
    db: DbSession,
) -> UserOut:
    """Return the authenticated user's identity and consent state."""

    if settings.is_production:
        user_repository = UserRepository(db)

        user = await user_repository.get_by_id(principal.user_id)
    else:
        user_repository = get_user_repository(settings)

        user = user_repository.get_by_id(principal.user_id)

    if user is None or not user.active:
        raise AuthenticationError("Authentication is required.")

    if settings.is_production:
        consent_repository = ConsentRepository(db)

        consents = await consent_repository.granted_for(user.id)
    else:
        consents = get_consent_repository(settings).granted_for(user.id)

    ordered_consents = sorted(
        consents,
        key=lambda consent: consent.value,
    )

    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=_normalise_role(user.role),
        consents=ordered_consents,
    )


def _after_commit(db: AsyncSession, apply: Callable[[], None]) -> None:
    """Run apply once db's transaction commits, and never if it rolls back."""
    session = db.sync_session
    pending = [True]

    def committed(_: Session) -> None:
        if pending:
            pending.clear()
            apply()

    def rolled_back(_: Session) -> None:
        pending.clear()

    event.listen(session, "after_commit", committed)
    event.listen(session, "after_rollback", rolled_back)


@auth.post(
    "/consent",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
)
@audit_action("CONSENT_UPDATED", commit=True)
async def record_consent(
    payload: ConsentRequest,
    request: Request,
    principal: CurrentUser,
    settings: AppSettings,
    db: DbSession,
) -> ConsentOut:
    """Consent is per-type and revocable.

    Revoking camera or microphone consent must stop collection immediately and
    must not reduce the student's engagement score.
    """

    if principal.role != Role.STUDENT and payload.consent_type != ConsentType.TERMS:
        raise PermissionError_(
            "Student monitoring permissions do not apply to this role.",
            {"invalid_consent_types": [payload.consent_type.value]},
        )

    if settings.is_production:
        repository = ConsentRepository(db)

        record = await repository.record(
            principal.user_id,
            payload.consent_type,
            payload.granted,
        )

        record_consent_type = ConsentType(record.consent_type)
    else:
        repository = get_consent_repository(settings)

        record = repository.record(
            principal.user_id,
            payload.consent_type,
            payload.granted,
        )

        record_consent_type = record.consent_type

    log.info(
        "security_event=%s user_id=%s consent_type=%s",
        ("CONSENT_GRANTED" if record.granted else "CONSENT_REVOKED"),
        principal.user_id,
        payload.consent_type.value,
    )

    # Live classes act on a decision at once, not at the user's next join.
    # A withdrawal is applied before anything else can happen. A grant is
    # read back from the store within this transaction and admitted only once
    # the transaction, audit record included, has committed (audit_action
    # commits it before responding), so a class never acts on a grant that
    # was not kept with its audit record. A withdrawal made meanwhile wins.
    if not record.granted:
        await classroom.withdraw_consent(principal.user_id, payload.consent_type)
    else:
        read_at = classroom.consents.version(principal.user_id)
        granted = await granted_consents(principal.user_id, settings, db)

        def admit() -> None:
            classroom.admit_consents(principal.user_id, granted, read_at)

        if settings.is_production:
            _after_commit(db, admit)
        else:
            admit()

    return ConsentOut(
        consent_type=record_consent_type,
        granted=record.granted,
        recorded_at=record.recorded_at,
    )


@admin.post(
    "/timetable",
    response_model=TimetableImportResult,
)
@audit_action("TIMETABLE_IMPORTED")
async def import_timetable(
    file: UploadFile,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> TimetableImportResult:
    """CSV or XLSX only. Structured data is parsed, never OCR'd."""

    raw = await _read_upload_with_limit(file)

    rows, rows_read = parse_timetable(
        file.filename or "",
        raw,
    )

    conflicts = detect_timetable_conflicts(rows)

    # Matched against the lecturers who have accounts. Nothing is stored yet:
    # turning a weekly slot into dated sessions is still to be decided.
    known_lecturers = await _names_of(db, Role.LECTURER)

    unmatched_lecturers, _ = match_names(
        [row.lecturer for row in rows],
        known_lecturers,
    )

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=conflicts,
        unmatched_lecturers=unmatched_lecturers,
        unmatched_students=[],
    )


@admin.post(
    "/roster",
    response_model=TimetableImportResult,
)
@audit_action("ROSTER_IMPORTED")
async def import_roster(
    file: UploadFile,
    principal: CurrentUser,
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> TimetableImportResult:
    """CSV or XLSX only, same reasoning as /timetable: no OCR path."""

    raw = await _read_upload_with_limit(file)

    rows, rows_read = parse_roster(
        file.filename or "",
        raw,
    )

    # Matched against the students who have accounts. Nothing is stored yet:
    # a student holds one enrolment (student.user_id is unique), so enrolling
    # from a roster would move students between courses.
    known_students = await _names_of(db, Role.STUDENT)

    unmatched_students, _ = match_names(
        [row.student_name for row in rows],
        known_students,
    )

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=[],
        unmatched_lecturers=[],
        unmatched_students=unmatched_students,
    )


async def _names_of(db: AsyncSession, role: Role) -> list[str]:
    """The names of every account with this role, for matching an import."""
    return list(await db.scalars(select(User.name).where(User.role == role.value)))


router.include_router(auth)
router.include_router(admin)
