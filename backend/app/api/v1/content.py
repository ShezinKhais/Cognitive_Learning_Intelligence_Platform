"""Lecture material and question routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  AI 1:    upload processing, extraction, question generation
  Cyber 2: review actions
  BBIS:    persistence and queries
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, UploadFile, status

from app.api.deps import CurrentUser, DbSession, Paginated
from app.core.errors import not_implemented
from app.schemas.common import Page
from app.schemas.content import (
    MaterialOut,
    QuestionBulkReviewRequest,
    QuestionOut,
    QuestionReviewRequest,
)

router = APIRouter(prefix="/materials", tags=["content"])


@router.post("", response_model=MaterialOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_material(
    file: UploadFile, principal: CurrentUser, db: DbSession
) -> MaterialOut:
    """Accepts PDF, PPTX, DOCX or TXT.

    Returns 202 immediately: processing runs in the background and reports
    progress over the WebSocket as `material.progress` events.
    """
    raise not_implemented("AI 1", "Phase 2")


@router.get("", response_model=Page[MaterialOut])
async def list_materials(
    principal: CurrentUser, db: DbSession, page: Paginated
) -> Page[MaterialOut]:
    raise not_implemented("BBIS", "Phase 2")


@router.get("/{material_id}", response_model=MaterialOut)
async def get_material(
    material_id: UUID, principal: CurrentUser, db: DbSession
) -> MaterialOut:
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
