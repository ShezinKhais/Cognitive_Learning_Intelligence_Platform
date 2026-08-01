"""Authentication, consent and administration routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  Cyber 1: authentication, consent
  Cyber 2: administrator console
"""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.core.errors import not_implemented
from app.schemas.identity import (
    ConsentOut,
    ConsentRequest,
    LoginRequest,
    TimetableImportResult,
    TokenResponse,
    UserOut,
)

router = APIRouter()

auth = APIRouter(prefix="/auth", tags=["auth"])
admin = APIRouter(prefix="/admin", tags=["admin"])


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
    """CSV or XLSX only. Structured data is parsed, never OCR'd."""
    raise not_implemented("Cyber 2", "Phase 1")


@admin.post("/roster", response_model=TimetableImportResult)
async def import_roster(
    file: UploadFile, principal: CurrentUser, db: DbSession
) -> TimetableImportResult:
    raise not_implemented("Cyber 2", "Phase 1")


router.include_router(auth)
router.include_router(admin)
