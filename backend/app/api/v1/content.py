"""Lecture material and question routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  AI 1:    upload processing, extraction, question generation
  Cyber 2: review actions
  BBIS:    persistence and queries
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, UploadFile, status

from app.api.deps import CurrentUser, DbSession, Paginated, require_roles
from app.core.errors import not_implemented
from app.schemas.common import Page
from app.schemas.content import (
    MaterialOut,
    MaterialStatus,
    QuestionBulkReviewRequest,
    QuestionOut,
    QuestionReviewRequest,
)
from app.schemas.identity import Role
from app.services.uploads import (
    get_background_processor,
    get_material_pipeline,
    get_material_storage,
    stream_upload,
)

router = APIRouter(prefix="/materials", tags=["content"])

DEFAULT_CONTENT_TYPE = "application/octet-stream"


@router.post(
    "",
    response_model=MaterialOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)
async def upload_material(file: UploadFile, principal: CurrentUser) -> MaterialOut:
    """Accepts PDF, PPTX, DOCX or TXT.

    Returns 202 immediately: processing runs in the background and reports
    progress over the WebSocket as `material.progress` events.
    """
    # This docstring is the public description in openapi.json, so the
    # implementation note stays out here: the request ends at the return
    # below, and nothing downstream may hold anything scoped to it. That is
    # why the file is written to storage rather than handed on as an open
    # handle, and why this handler takes no database session.
    material_id = uuid4()
    storage = get_material_storage()
    pipeline = get_material_pipeline()

    # Writing the file is the only part the lecturer waits for. An unsupported
    # extension or an oversized upload is refused here, while there is still a
    # response to refuse it with.
    stored = await storage.save(material_id, file.filename or "", stream_upload(file))

    async def work() -> None:
        await pipeline.run(stored, principal.user_id)

    get_background_processor().submit(material_id, work)

    # Built from what the request knows. Persisting the row is BBIS's #36, and
    # until it lands the counts stay null exactly as they would while a real
    # row is still processing.
    return MaterialOut(
        id=material_id,
        filename=stored.filename,
        content_type=file.content_type or DEFAULT_CONTENT_TYPE,
        size_bytes=stored.size_bytes,
        status=MaterialStatus.PENDING,
        uploaded_at=datetime.now(UTC),
    )


@router.get("", response_model=Page[MaterialOut])
async def list_materials(
    principal: CurrentUser, db: DbSession, page: Paginated
) -> Page[MaterialOut]:
    raise not_implemented("BBIS", "Phase 2")


@router.get("/{material_id}", response_model=MaterialOut)
async def get_material(material_id: UUID, principal: CurrentUser, db: DbSession) -> MaterialOut:
    raise not_implemented("BBIS", "Phase 2")


@router.get("/{material_id}/questions", response_model=Page[QuestionOut])
async def list_questions(
    material_id: UUID, principal: CurrentUser, db: DbSession, page: Paginated
) -> Page[QuestionOut]:
    raise not_implemented("AI 1", "Phase 2")


@router.patch("/{material_id}/questions/{question_id}", response_model=QuestionOut)
async def review_question(
    material_id: UUID,
    question_id: UUID,
    payload: QuestionReviewRequest,
    principal: CurrentUser,
    db: DbSession,
) -> QuestionOut:
    """Approve, edit or reject a generated question.

    No question reaches a student without passing through here.
    """
    raise not_implemented("Cyber 2", "Phase 2")


@router.post("/{material_id}/questions:bulk", response_model=list[QuestionOut])
async def bulk_review_questions(
    material_id: UUID,
    payload: QuestionBulkReviewRequest,
    principal: CurrentUser,
    db: DbSession,
) -> list[QuestionOut]:
    """Backs the 'approve all' and 'stage N questions' actions."""
    raise not_implemented("Cyber 2", "Phase 2")
