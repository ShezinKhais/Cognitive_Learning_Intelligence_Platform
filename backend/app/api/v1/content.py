"""Lecture material and question routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  AI 1:     upload processing, extraction, question generation
  Cyber 1:  upload security validation
  Cyber 2:  review actions
  BBIS:     persistence and queries
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, status

from app.api.deps import CurrentUser, DbSession, Paginated, require_consents, require_roles
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.repositories.material_repository import MaterialRepository
from app.repositories.question_repository import QuestionRepository
from app.schemas.common import Page
from app.schemas.content import (
    MaterialOut,
    MaterialStatus,
    QuestionBulkReviewRequest,
    QuestionBulkReviewResult,
    QuestionOut,
    QuestionReviewRequest,
)
from app.schemas.identity import ConsentType, Role
from app.services.extraction import CONTENT_TYPES
from app.services.question_ownership import filter_owned_questions, get_owned_question
from app.services.uploads import accept_upload

# Every route here, the review actions included, is lecturer and admin work,
# so the role guard sits on the router. Ownership (app.services.question_
# ownership) narrows a lecturer down to their own sessions on top of this;
# neither check alone is enough -- role without ownership would let any
# lecturer touch any other lecturer's questions, and ownership without role
# would let a user whose account still matches a session's instructor_id
# keep acting on it even after their role changed away from lecturer.
router = APIRouter(
    prefix="/materials",
    tags=["content"],
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
        # The same terms gate /sessions and /admin enforce. The lecturer pages
        # redirect to /consent first, but that is the frontend's courtesy, not
        # a control: without this an unconsented token uploaded with a 202.
        Depends(require_consents(ConsentType.TERMS)),
    ],
)


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
async def upload_material(file: UploadFile, principal: CurrentUser) -> MaterialOut:
    """Accepts PDF, PPTX, DOCX or TXT.

    Returns 202 immediately after the uploaded file passes security validation.
    Processing then runs in the background and reports progress over the
    WebSocket as `material.progress` events.
    """
    stored = await accept_upload(file, principal.user_id)

    # Built from what the request knows. Persisting the row is BBIS's #36, and
    # until it lands the counts stay null exactly as they would while a real
    # row is still processing.
    return MaterialOut(
        id=stored.material_id,
        filename=stored.filename,
        # The type of what was stored, decided by the validated extension. The
        # client's Content-Type header is whatever the browser chose to send.
        content_type=CONTENT_TYPES[stored.extension],
        size_bytes=stored.size_bytes,
        status=MaterialStatus.PENDING,
        uploaded_at=datetime.now(UTC),
    )


@router.get(
    "",
    response_model=Page[MaterialOut],
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
    ],
)
async def list_materials(
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[MaterialOut]:
    uploaded_by_user_id = None if principal.is_(Role.ADMIN) else principal.user_id
    repository = MaterialRepository(db)
    materials, total = await repository.list_page(
        limit=page.limit,
        offset=page.offset,
        uploaded_by_user_id=uploaded_by_user_id,
    )

    return Page[MaterialOut](
        items=[
            MaterialOut.model_validate(material, from_attributes=True) for material in materials
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{material_id}",
    response_model=MaterialOut,
    dependencies=[
        Depends(require_roles(Role.LECTURER, Role.ADMIN)),
    ],
)
async def get_material(
    material_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> MaterialOut:
    uploaded_by_user_id = None if principal.is_(Role.ADMIN) else principal.user_id
    repository = MaterialRepository(db)
    material = await repository.get_by_id(
        material_id,
        uploaded_by_user_id=uploaded_by_user_id,
    )

    if material is None:
        raise NotFoundError(
            "Material was not found.",
            {"material_id": str(material_id)},
        )

    return MaterialOut.model_validate(material, from_attributes=True)


@router.get("/{material_id}/questions", response_model=Page[QuestionOut])
async def list_questions(
    material_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[QuestionOut]:
    """The review queue for a material.

    Lecturer/admin only, same as the mutation routes --
    QuestionOut carries correct_option, which must never reach a student or
    a lecturer who doesn't teach the sessions this material's questions
    belong to. A lecturer sees only their own; an admin sees everything.
    """
    repo = QuestionRepository(db)
    questions, total = await repo.list_owned_by_material(
        material_id,
        principal.user_id,
        is_admin=principal.role == Role.ADMIN,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[_to_question_out(q) for q in questions],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/{material_id}/questions/{question_id}", response_model=QuestionOut)
async def review_question(
    material_id: UUID,
    question_id: UUID,
    payload: QuestionReviewRequest,
    principal: CurrentUser,
    db: DbSession,
) -> QuestionOut:
    """Approve, edit or reject a generated question. No question reaches a
    student without passing through here.
    """
    # A lecturer may only act on questions belonging to a session they are
    # the instructor of and that belong to material_id; admins may act on
    # any question. A question that exists but belongs to a different
    # material, or a different lecturer's session, is rejected the same
    # way a nonexistent question is -- see app.services.question_ownership
    # for why. Invalid status transitions (e.g. skipping straight to
    # delivered, or editing a staged/delivered question) are rejected by
    # the repository with a 409; see QuestionRepository.apply_review.
    repo = QuestionRepository(db)
    question = await get_owned_question(question_id, principal, repo, material_id=material_id)

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


@router.post("/{material_id}/questions:bulk", response_model=QuestionBulkReviewResult)
async def bulk_review_questions(
    material_id: UUID,
    payload: QuestionBulkReviewRequest,
    principal: CurrentUser,
    db: DbSession,
) -> QuestionBulkReviewResult:
    """Backs the 'approve all' and 'stage N questions' actions."""
    # Same ownership and material-scoping rule as review_question, applied
    # per question. A question that is unowned, belongs to a different
    # material, or whose current status doesn't allow the requested
    # transition, is skipped rather than failing the whole batch -- one
    # stale or reassigned row should not block the rest of a bulk action.
    # Every skipped id is reported back in skipped_ids rather than silently
    # dropped, so a lecturer can tell "all N approved" from "N approved, M
    # skipped" instead of a response that looks identical either way.
    repo = QuestionRepository(db)
    owned, rejected = await filter_owned_questions(
        payload.question_ids, principal, repo, material_id=material_id
    )

    updated = []
    skipped_ids = list(rejected)
    for question in owned:
        try:
            updated.append(
                await repo.apply_review(
                    question,
                    status=payload.status.value,
                    reviewer_id=principal.user_id,
                )
            )
        except (ConflictError, ValidationError):
            # A bad transition or a malformed answer key on one question
            # must not fail the rest of the batch -- same treatment as an
            # unowned or wrong-material id, for the same reason: "approve
            # all" is one convenient action, not an all-or-nothing
            # transaction that one stale or malformed row can block.
            skipped_ids.append(question.question_id)

    return QuestionBulkReviewResult(
        updated=[_to_question_out(q) for q in updated],
        skipped_ids=skipped_ids,
    )
