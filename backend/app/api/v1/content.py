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
from app.repositories.question_repository import QuestionRepository
from app.schemas.common import Page
from app.schemas.content import (
    MaterialOut,
    QuestionBulkReviewRequest,
    QuestionOut,
    QuestionReviewRequest,
)
from app.services.question_ownership import filter_owned_questions, get_owned_question

router = APIRouter(prefix="/materials", tags=["content"])


def _to_question_out(question) -> QuestionOut:  # noqa: ANN001 - app.models.Question
    return QuestionOut(
        id=question.question_id,
        material_id=question.source_material_id,
        type=question.question_type,
        status=question.status,
        difficulty=question.difficulty,
        prompt=question.question_text,
        options=question.options,
        correct_option=question.correct_option,
        topic=question.topic,
        source_slide=question.source_slide,
        source_excerpt=question.source_excerpt,
    )


@router.post("", response_model=MaterialOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_material(file: UploadFile, principal: CurrentUser, db: DbSession) -> MaterialOut:
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

    No question reaches a student without passing through here. A lecturer
    may only act on questions belonging to a session they are the
    instructor of; admins may act on any question. material_id is not used
    to scope the lookup (question_id already uniquely identifies the row)
    but is kept in the path per the frozen contract -- it also means a
    request against the wrong material_id for a real question_id still
    succeeds, which mirrors how the id, not the path, is the source of
    truth elsewhere in this API.
    """
    repo = QuestionRepository(db)
    question = await get_owned_question(question_id, principal, repo)

    updated = await repo.apply_review(
        question,
        status=payload.status.value,
        reviewer_id=principal.user_id,
        prompt=payload.prompt,
        options=payload.options,
        correct_option=payload.correct_option,
        difficulty=payload.difficulty.value if payload.difficulty else None,
    )

    return _to_question_out(updated)


@router.post("/{material_id}/questions:bulk", response_model=list[QuestionOut])
async def bulk_review_questions(
    material_id: UUID,
    payload: QuestionBulkReviewRequest,
    principal: CurrentUser,
    db: DbSession,
) -> list[QuestionOut]:
    """Backs the 'approve all' and 'stage N questions' actions.

    Same ownership rule as review_question, applied per question: any id in
    the request that does not exist, or belongs to another lecturer's
    session, is silently skipped rather than failing the whole batch. A
    lecturer selecting "approve all" on their own review queue should not
    have that fail because one row in the batch turned out stale or
    reassigned between page load and submit.
    """
    repo = QuestionRepository(db)
    owned, _rejected = await filter_owned_questions(payload.question_ids, principal, repo)

    updated = [
        await repo.apply_review(
            question,
            status=payload.status.value,
            reviewer_id=principal.user_id,
        )
        for question in owned
    ]

    return [_to_question_out(q) for q in updated]
