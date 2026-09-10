"""Authentication, consent and administration routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  Cyber 1: authentication, consent
  Cyber 2: administrator console
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, UploadFile, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    require_roles,
)
from app.auth.login_security import PersistentLoginSecurityStore
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
from app.repositories.consent_repository import ConsentRepository
from app.repositories.user_repository import UserRepository
from fastapi import APIRouter, Depends, UploadFile, status

from app.api.deps import CurrentUser, DbSession, require_roles
from app.core.config import get_settings
from app.core.errors import ValidationError, not_implemented
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

router = APIRouter()

auth = APIRouter(prefix="/auth", tags=["auth"])
# Every route under /admin requires the ADMIN role. Cyber 1 owns the ownership
# checks inside require_roles (Phase 1); this is the "protected staff routes"
# requirement from the Phase 1 plan applied at the router level rather than
# repeated per-handler.
admin = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(Role.ADMIN))]
)


def _reject_if_too_large(file: UploadFile) -> None:
    """Reject an oversized upload before it's read into memory.

    UploadFile.size comes from the part's Content-Length and is known before
    any bytes are read, so a client claiming a too-large body is rejected
    immediately. It can be None (some clients omit it), so this is a
    best-effort first line of defense, not the only check - the caller still
    checks len(raw) after reading, for the case where size wasn't reported.
    """
    max_bytes = get_settings().max_upload_bytes
    if file.size is not None and file.size > max_bytes:
        raise ValidationError(
            "File exceeds the maximum upload size.",
            {"max_bytes": max_bytes, "reported_size": file.size},
        )

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


@auth.post(
    "/consent",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
)
@audit_action("CONSENT_UPDATED")
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
            ("Student monitoring permissions do not apply to this role."),
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

    return ConsentOut(
        consent_type=record_consent_type,
        granted=record.granted,
        recorded_at=record.recorded_at,
    )


@admin.post(
    "/timetable",
    response_model=TimetableImportResult,
)
async def import_timetable(
    file: UploadFile,
    principal: CurrentUser,
    db: DbSession,
) -> TimetableImportResult:
    """CSV or XLSX only. Structured data is parsed, never OCR'd."""
    # TODO(Cyber 2 + BBIS): once Session/Lecturer ORM models exist, replace the
    # known_lecturers placeholder below with a real query, and persist rows
    # as Session rows instead of just counting them. Until then this
    # validates, parses and reports conflicts without writing anything -
    # still useful on its own for an admin sanity-checking a file before the
    # write path exists.
    _reject_if_too_large(file)
    raw = await file.read()
    if len(raw) > get_settings().max_upload_bytes:
        raise ValidationError(
            "File exceeds the maximum upload size.",
            {"max_bytes": get_settings().max_upload_bytes},
        )

    rows, rows_read = parse_timetable(file.filename or "", raw)

    conflicts = detect_timetable_conflicts(rows)

    # Placeholder until BBIS's models land - see TODO above.
    known_lecturers: list[str] = []
    unmatched_lecturers, _ = match_names([r.lecturer for r in rows], known_lecturers)

    sessions_created = 0  # becomes a real count once rows are persisted

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=sessions_created,
        conflicts=conflicts,
        unmatched_lecturers=unmatched_lecturers,
        unmatched_students=[],
    )

    raw = await _read_upload_with_limit(file)

    rows, rows_read = parse_timetable(
        file.filename or "",
        raw,
    )

    conflicts = detect_timetable_conflicts(rows)

    # Placeholder until the final BBIS persistence integration.
    known_lecturers: list[str] = []

    unmatched_lecturers, _ = match_names(
        [row.lecturer for row in rows],
        known_lecturers,
    )

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=conflicts,
        unmatched_lecturers=(unmatched_lecturers),
        unmatched_students=[],
    )


@admin.post(
    "/roster",
    response_model=TimetableImportResult,
)
async def import_roster(
    file: UploadFile,
    principal: CurrentUser,
    db: DbSession,
) -> TimetableImportResult:
    """CSV or XLSX only, same reasoning as /timetable: no OCR path."""

    raw = await _read_upload_with_limit(file)

    rows, rows_read = parse_roster(
        file.filename or "",
        raw,
    )

    # Placeholder until the final BBIS persistence integration.
    known_students: list[str] = []

    unmatched_students, _ = match_names(
        [row.student_name for row in rows],
        known_students,
    )
    # TODO(Cyber 2 + BBIS): swap known_students for a real query against
    # enrolled students once the models exist, and persist matched rows as
    # roster/enrollment records instead of just counting them.
    _reject_if_too_large(file)
    raw = await file.read()
    if len(raw) > get_settings().max_upload_bytes:
        raise ValidationError(
            "File exceeds the maximum upload size.",
            {"max_bytes": get_settings().max_upload_bytes},
        )

    rows, rows_read = parse_roster(file.filename or "", raw)

    # Placeholder until BBIS's models land - see TODO above.
    known_students: list[str] = []
    unmatched_students, _ = match_names([r.student_name for r in rows], known_students)

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=[],
        unmatched_lecturers=[],
        unmatched_students=(unmatched_students),
        unmatched_students=unmatched_students,
    )


router.include_router(auth)
router.include_router(admin)
