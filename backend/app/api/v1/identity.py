"""Authentication, consent and administration routes.

Contract frozen in Phase 1. Handler bodies are owned by:
Cyber 1: authentication, consent
Cyber 2: administrator console
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, UploadFile, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    require_consents,
    require_roles,
)
from app.auth.store import (
    get_consent_repository,
    get_user_repository,
)
from app.core.errors import AuthenticationError, PermissionError_
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    verify_password,
)
from app.schemas.identity import (
    ConsentBatchOut,
    ConsentBatchRequest,
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


@auth.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    payload: LoginRequest,
    settings: AppSettings,
) -> TokenResponse:
    repository = get_user_repository(settings)
    user = repository.get_by_email(str(payload.email))

    # Always verify a password hash so unknown emails do not return
    # noticeably faster than known accounts.
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH

    password_valid = verify_password(
        payload.password,
        password_hash,
    )

    if user is None:
        log.warning("security_event=LOGIN_FAILED reason=invalid_credentials")
        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    if repository.is_locked(user.id):
        log.warning(
            "security_event=LOGIN_FAILED user_id=%s reason=account_locked",
            user.id,
        )
        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    if not password_valid:
        locked = repository.record_failed_login(user.id)

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

    repository.reset_failed_logins(user.id)

    token, expires_in = create_access_token(
        user_id=user.id,
        role=user.role,
        email=user.email,
        settings=settings,
    )

    log.info(
        "security_event=LOGIN_SUCCEEDED user_id=%s role=%s",
        user.id,
        user.role.value,
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=user.role,
    )


@auth.get(
    "/me",
    response_model=UserOut,
)
async def me(
    principal: CurrentUser,
    settings: AppSettings,
) -> UserOut:
    user = get_user_repository(settings).get_by_id(principal.user_id)

    if user is None or not user.active:
        raise AuthenticationError("Authentication is required.")

    consents = sorted(
        get_consent_repository().granted_for(user.id),
        key=lambda consent: consent.value,
    )

    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        consents=consents,
    )


@auth.post(
    "/consent",
    response_model=ConsentOut | ConsentBatchOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_consent(
    payload: ConsentRequest | ConsentBatchRequest,
    principal: CurrentUser,
) -> ConsentOut | ConsentBatchOut:
    """Record one consent decision or an atomic batch."""

    if isinstance(
        payload,
        ConsentBatchRequest,
    ):
        if principal.role != Role.STUDENT:
            invalid_types = [
                consent.consent_type.value
                for consent in payload.consents
                if consent.consent_type != ConsentType.TERMS
            ]

            if invalid_types:
                raise PermissionError_(
                    ("Student monitoring permissions do not apply to this role."),
                    {
                        "invalid_consent_types": invalid_types,
                    },
                )

        repository = get_consent_repository()

        records = repository.record_many(
            principal.user_id,
            [
                (
                    consent.consent_type,
                    consent.granted,
                )
                for consent in payload.consents
            ],
        )

        for record in records:
            log.info(
                "security_event=%s user_id=%s consent_type=%s",
                ("CONSENT_GRANTED" if record.granted else "CONSENT_REVOKED"),
                principal.user_id,
                record.consent_type.value,
            )

        return ConsentBatchOut(
            consents=[
                ConsentOut(
                    consent_type=(record.consent_type),
                    granted=record.granted,
                    recorded_at=(record.recorded_at),
                )
                for record in records
            ]
        )

    if principal.role != Role.STUDENT and payload.consent_type != ConsentType.TERMS:
        raise PermissionError_(
            ("Student monitoring permissions do not apply to this role."),
            {"invalid_consent_types": [payload.consent_type.value]},
        )

    record = get_consent_repository().record(
        principal.user_id,
        payload.consent_type,
        payload.granted,
    )

    log.info(
        "security_event=%s user_id=%s consent_type=%s",
        ("CONSENT_GRANTED" if record.granted else "CONSENT_REVOKED"),
        principal.user_id,
        payload.consent_type.value,
    )

    return ConsentOut(
        consent_type=record.consent_type,
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
) -> TimetableImportResult:
    """Import a timetable CSV or XLSX file."""

    raw = await file.read()

    rows, rows_read = parse_timetable(
        file.filename or "",
        raw,
    )

    conflicts = detect_timetable_conflicts(rows)

    # TODO(Cyber 2 + BBIS):
    # Replace with real lecturer lookup and persistence.
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
) -> TimetableImportResult:
    """Import a roster CSV or XLSX file."""

    raw = await file.read()

    rows, rows_read = parse_roster(
        file.filename or "",
        raw,
    )

    # TODO(Cyber 2 + BBIS):
    # Replace with real student lookup and persistence.
    known_students: list[str] = []

    unmatched_students, _ = match_names(
        [row.student_name for row in rows],
        known_students,
    )

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=[],
        unmatched_lecturers=[],
        unmatched_students=(unmatched_students),
    )


router.include_router(auth)
router.include_router(admin)
