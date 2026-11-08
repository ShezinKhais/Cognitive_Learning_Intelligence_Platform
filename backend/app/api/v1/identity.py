"""Authentication, consent and administration routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  Cyber 1: authentication, consent
  Cyber 2: administrator console
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, Response, UploadFile, status
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    require_consents,
    require_roles,
)
from app.auth.address_limiter import get_login_address_limiter
from app.auth.login_security import PersistentLoginSecurityStore
from app.auth.service import granted_consents, renew_token
from app.auth.store import (
    get_consent_repository,
    get_login_security_store,
    get_user_repository,
)
from app.core.audit import audit_action
from app.core.config import Settings, get_settings
from app.core.errors import (
    AuthenticationError,
    PermissionError_,
    ValidationError,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    verify_password,
)
from app.realtime.classroom import classroom
from app.repositories.consent_repository import ConsentRepository
from app.repositories.teams_user_mapping_repository import TeamsUserMappingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.identity import (
    ConsentOut,
    ConsentRequest,
    ConsentType,
    LoginRequest,
    Role,
    TeamsSignInRequest,
    TimetableImportResult,
    TokenResponse,
    UserOut,
)
from app.services import course_imports
from app.services.teams_sso import EntraIdentity, verify_entra_token
from app.services.timetable_import import (
    detect_timetable_conflicts,
    parse_roster,
    parse_timetable,
)

log = logging.getLogger("clip.security")

GENERIC_LOGIN_ERROR = "Incorrect email or password."

# The refresh token's cookie. httpOnly, so no script on the page can read it,
# and scoped to the auth routes, so it travels with nothing else.
REFRESH_COOKIE = "clip_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
# Refresh and sign-out must carry this header. A page on another site cannot
# add a custom header without a CORS preflight, which production refuses, so
# the cookie alone never refreshes or signs anyone out.
REFRESH_HEADER = "X-CLIP-Refresh"


def _set_refresh_cookie(response: Response, token: str, max_age: int, settings: Settings) -> None:
    if settings.is_production:
        # A Teams tab is a cross-site iframe, where only a SameSite=None
        # cookie is sent; Partitioned keys it to the embedding site. Written
        # by hand because Starlette sets Partitioned only on Python 3.14 and
        # the image runs 3.12. A JWT is base64url and dots, so it needs no
        # quoting.
        response.headers.append(
            "set-cookie",
            f"{REFRESH_COOKIE}={token}; Max-Age={max_age}; Path={REFRESH_COOKIE_PATH}; "
            "Secure; HttpOnly; SameSite=None; Partitioned",
        )
    else:
        # Development runs on plain http, where a Secure cookie is dropped.
        response.set_cookie(
            REFRESH_COOKIE,
            token,
            max_age=max_age,
            path=REFRESH_COOKIE_PATH,
            httponly=True,
            samesite="lax",
        )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    # An empty value that expires at once replaces the cookie. It has to carry
    # the same attributes, Partitioned included, or it is a different cookie.
    _set_refresh_cookie(response, "", 0, settings)


def _require_refresh_header(request: Request) -> None:
    if request.headers.get(REFRESH_HEADER) != "1":
        raise AuthenticationError("Sign in again.")


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
    responses={
        429: {"description": "Too many failed sign-ins from this address recently."},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: AppSettings,
    db: DbSession,
) -> TokenResponse:
    """Authenticate a user, return a bearer token and set the refresh cookie.

    An address with too many recent failures is refused with 429 before the
    password is checked. Every failure, whatever the reason, counts against
    the address.
    """

    ip_address = request.client.host if request.client is not None else "unknown"
    limiter = get_login_address_limiter()
    limiter.begin(ip_address)

    try:
        token = await _authenticate(payload, settings, db)
    except AuthenticationError:
        limiter.record_failure(ip_address)
        raise
    finally:
        limiter.end(ip_address)

    claims = decode_access_token(token.access_token, settings)
    refresh_token, max_age = create_refresh_token(
        user_id=claims.user_id,
        role=claims.role,
        email=claims.email,
        settings=settings,
        auth_time=claims.auth_time,
    )
    _set_refresh_cookie(response, refresh_token, max_age, settings)
    return token


async def _authenticate(
    payload: LoginRequest,
    settings: Settings,
    db: AsyncSession,
) -> TokenResponse:
    """Check the credentials and return a bearer token.

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


@auth.post(
    "/teams",
    response_model=TokenResponse,
    responses={
        429: {"description": "Too many failed sign-ins from this address recently."},
        403: {"description": "The Microsoft account has no C.L.I.P account."},
        503: {"description": "Teams sign-in is not configured, or Microsoft is unreachable."},
    },
)
async def teams_sign_in(
    payload: TeamsSignInRequest,
    request: Request,
    response: Response,
    settings: AppSettings,
    db: DbSession,
) -> TokenResponse:
    """Sign in with the Microsoft account Teams is signed in with.

    The tab sends the Entra token Teams gave it. The account must already
    exist in C.L.I.P; see app/services/teams_sso.py.
    """
    ip_address = request.client.host if request.client is not None else "unknown"
    limiter = get_login_address_limiter()
    limiter.begin(ip_address)
    try:
        identity = await verify_entra_token(payload.token, settings)
        user = await _teams_account(identity, settings, db)
    except (AuthenticationError, PermissionError_):
        limiter.record_failure(ip_address)
        raise
    finally:
        limiter.end(ip_address)

    role = _normalise_role(user.role)
    token, expires_in = create_access_token(
        user_id=user.id, role=role, email=user.email, settings=settings
    )
    claims = decode_access_token(token, settings)
    refresh_token, max_age = create_refresh_token(
        user_id=user.id,
        role=role,
        email=user.email,
        settings=settings,
        auth_time=claims.auth_time,
    )
    _set_refresh_cookie(response, refresh_token, max_age, settings)
    log.info("security_event=LOGIN_SUCCEEDED user_id=%s role=%s method=teams", user.id, role.value)
    return TokenResponse(access_token=token, expires_in=expires_in, role=role)


TEAMS_NO_ACCOUNT = (
    "This Microsoft account has no C.L.I.P account yet. Ask your C.L.I.P administrator to add it."
)


async def _teams_account(identity: EntraIdentity, settings: Settings, db: AsyncSession):
    """The active account for a validated Entra identity, linking it the
    first time by sign-in name."""
    if settings.is_production:
        users = UserRepository(db)

        async def by_id(user_id):
            return await users.get_by_id(user_id)

        async def by_email(email):
            return await users.get_by_email(email)
    else:
        dev = get_user_repository(settings)

        async def by_id(user_id):
            return dev.get_by_id(user_id)

        async def by_email(email):
            return dev.get_by_email(email)

    mappings = TeamsUserMappingRepository(db)
    linked = await mappings.user_for(tenant_id=identity.tenant_id, teams_user_id=identity.object_id)
    user = await by_id(linked) if linked is not None else None
    if user is None and identity.sign_in_name:
        user = await by_email(identity.sign_in_name)
        if user is not None:
            await mappings.link_user(
                tenant_id=identity.tenant_id, teams_user_id=identity.object_id, user_id=user.id
            )
            log.info("audit_event=TEAMS_USER_LINKED user_id=%s method=sso", user.id)
    if user is None:
        log.warning("security_event=LOGIN_FAILED reason=teams_no_account")
        raise PermissionError_(TEAMS_NO_ACCOUNT)
    if not user.active:
        log.warning("security_event=LOGIN_FAILED user_id=%s reason=inactive", user.id)
        raise AuthenticationError(GENERIC_LOGIN_ERROR)
    return user


@auth.post(
    "/refresh",
    response_model=TokenResponse,
)
async def refresh(
    request: Request,
    settings: AppSettings,
    db: DbSession,
) -> TokenResponse:
    """A fresh access token for the holder of the refresh cookie.

    The client calls this shortly before its token expires, so a class longer
    than the token's lifetime is not interrupted by a sign-in, and on load,
    since it keeps the access token in memory only. The account is checked
    again, and the sign-in itself still ends max_sign_in_hours after the
    password was typed. An access token cannot be refreshed: one taken from
    the page ends at its own expiry.
    """

    _require_refresh_header(request)
    cookie = request.cookies.get(REFRESH_COOKIE)
    if not cookie:
        raise AuthenticationError("Sign in again.")

    try:
        renewed = await renew_token(cookie, settings, db)
    except TokenValidationError as exc:
        log.warning(
            "security_event=TOKEN_REFRESH_REFUSED reason=%s",
            str(exc),
        )

        raise AuthenticationError("Sign in again.") from exc

    log.info(
        "security_event=TOKEN_REFRESHED user_id=%s role=%s",
        renewed.user.id,
        renewed.user.role.value,
    )

    return TokenResponse(
        access_token=renewed.access_token,
        expires_in=renewed.expires_in,
        role=renewed.user.role,
    )


@auth.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(
    request: Request,
    settings: AppSettings,
) -> Response:
    """Drop the refresh cookie, so the sign-in cannot be renewed.

    An access token already issued still works until its expiry, as before:
    tokens are not revoked.
    """

    _require_refresh_header(request)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    log.info("security_event=SIGNED_OUT")
    return response


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

    # Each row's lecturer teaches its course. Turning a weekly slot into
    # dated sessions is still to be decided, so no session is created.
    outcome = await course_imports.apply_timetable(db, rows)
    await db.commit()

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=conflicts,
        unmatched_lecturers=outcome.unmatched_lecturers,
        unmatched_students=[],
        courses_created=outcome.courses_created,
        lecturers_assigned=outcome.lecturers_assigned,
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

    # Each row puts the student on the course, found by email. A student
    # can be on several courses, so nobody is moved off another one.
    outcome = await course_imports.apply_roster(db, rows)
    await db.commit()

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=[],
        unmatched_lecturers=[],
        unmatched_students=outcome.unmatched_students,
        courses_created=outcome.courses_created,
        students_enrolled=outcome.students_enrolled,
    )


router.include_router(auth)
router.include_router(admin)
