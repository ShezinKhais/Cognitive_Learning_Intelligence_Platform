"""Authentication, consent and administration routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  Cyber 1: authentication, consent
  Cyber 2: administrator console
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile, status
from app.core.config import get_settings
from app.api.deps import CurrentUser, DbSession, require_roles
from app.core.errors import not_implemented
from app.schemas.identity import (
    ConsentOut,
    ConsentRequest,
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

router = APIRouter()

auth = APIRouter(prefix="/auth", tags=["auth"])
# Every route under /admin requires the ADMIN role. Cyber 1 owns the ownership
# checks inside require_roles (Phase 1); this is the "protected staff routes"
# requirement from the Phase 1 plan applied at the router level rather than
# repeated per-handler.
admin = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles(Role.ADMIN))]
)


@auth.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    raise not_implemented("Cyber 1", "Phase 1")


@auth.get("/me", response_model=UserOut)
async def me(principal: CurrentUser, db: DbSession) -> UserOut:
    raise not_implemented("Cyber 1", "Phase 1")


@auth.post("/consent", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def record_consent(
    payload: ConsentRequest, principal: CurrentUser, db: DbSession
) -> ConsentOut:
    """Consent is per-type and revocable.

    Revoking camera or microphone consent must stop collection immediately and
    must not reduce the student's engagement score.
    """
    raise not_implemented("Cyber 1", "Phase 1")


@admin.post("/timetable", response_model=TimetableImportResult)
async def import_timetable(
    file: UploadFile, principal: CurrentUser, db: DbSession
) -> TimetableImportResult:
    """CSV or XLSX only. Structured data is parsed, never OCR'd.

    TODO(Cyber 2 + BBIS): once Session/Lecturer ORM models exist, replace the
    `known_lecturers = []` placeholder below with a real query, and persist
    `rows` as Session rows instead of just counting them. Until then this
    validates, parses and reports conflicts without writing anything —
    still useful on its own for an admin sanity-checking a file before the
    write path exists.
    """
    raw = await file.read()
    rows, rows_read = parse_timetable(file.filename or "", raw)

    conflicts = detect_timetable_conflicts(rows)

    # Placeholder until BBIS's models land -see TODO above.
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


@admin.post("/roster", response_model=TimetableImportResult)
async def import_roster(
    file: UploadFile, principal: CurrentUser, db: DbSession
) -> TimetableImportResult:
    """CSV or XLSX only, same reasoning as /timetable: no OCR path.

    TODO(Cyber 2 + BBIS): swap `known_students = []` for a real query against
    enrolled students once the models exist, and persist matched rows as
    roster/enrollment records instead of just counting them.
    """
  raw = await file.read()
    if len(raw) > get_settings().max_upload_bytes:
        raise ValidationError(
            "File exceeds the maximum upload size.",
            {"max_bytes": get_settings().max_upload_bytes},
        )

    rows, rows_read = parse_timetable(file.filename or "", raw)

    return TimetableImportResult(
        rows_read=rows_read,
        sessions_created=0,
        conflicts=[],
        unmatched_lecturers=[],
        unmatched_students=unmatched_students,
    )


router.include_router(auth)
router.include_router(admin)
