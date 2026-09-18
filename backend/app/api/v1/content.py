"""Lecture material and question routes.

Contract frozen in Phase 1. Handler bodies are owned by:
  AI 1:     upload processing, extraction, question generation
  Cyber 1:  upload security validation
  Cyber 2:  review actions
  BBIS:     persistence and queries
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, UploadFile, status

from app.api.deps import CurrentUser, DbSession, Paginated, require_roles
from app.core.errors import NotFoundError, not_implemented
from app.repositories.material_repository import MaterialRepository
from app.schemas.common import Page
from app.schemas.content import (
    MaterialOut,
    MaterialStatus,
    QuestionBulkReviewRequest,
    QuestionOut,
    QuestionReviewRequest,
)
from app.schemas.identity import Role
from app.services.upload_security import validate_uploaded_file
from app.services.uploads import (
    get_background_processor,
    get_material_pipeline,
    get_material_storage,
    stream_upload,
)

router = APIRouter(
    prefix="/materials",
    tags=["content"],
    dependencies=[Depends(require_roles(Role.LECTURER, Role.ADMIN))],
)

DEFAULT_CONTENT_TYPE = "application/octet-stream"

# The response reports the type of what was stored, which is decided by the
# validated extension. The client's Content-Type header is whatever the browser
# or script chose to send, so echoing it let a .txt upload come back labelled
# text/html.
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}


@router.post("", response_model=MaterialOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_material(file: UploadFile, principal: CurrentUser) -> MaterialOut:
    """Accepts PDF, PPTX, DOCX or TXT.

    Returns 202 immediately after the uploaded file passes security validation.
    Processing then runs in the background and reports progress over the
    WebSocket as `material.progress` events.
    """
    # The request ends after the 202 response, so the uploaded file has to be
    # written to storage before background processing begins.
    material_id = uuid4()
    storage = get_material_storage()
    pipeline = get_material_pipeline()

    # Storage already enforces:
    # - allowed extensions
    # - maximum upload size
    # - non-empty uploads
    # - safe server-side filenames
    stored = await storage.save(
        material_id,
        file.filename or "",
        stream_upload(file),
    )

    # Cyber 1 security validation.
    #
    # A valid filename extension is not enough. The stored bytes are checked
    # before any background processing starts so that files such as an
    # executable renamed to lecture.pdf are rejected during the request.
    #
    # If validation fails, remove the file immediately so a malicious or
    # malformed upload is never left in material storage.
    try:
        async with storage.materialise(stored) as path:
            validate_uploaded_file(
                str(path),
                stored.extension,
                file.content_type,
            )
    except Exception:
        await storage.delete(material_id)
        raise

    async def work() -> None:
        await pipeline.run(stored, principal.user_id)

    async def interrupted() -> None:
        await pipeline.abandon(material_id, principal.user_id)

    get_background_processor().submit(material_id, work, on_cancel=interrupted)

    # Built from what the request knows. Persisting the row is BBIS's Phase 2
    # responsibility. Until that lands, page and chunk counts remain unset
    # while the material is processing.
    return MaterialOut(
        id=material_id,
        filename=stored.filename,
        content_type=CONTENT_TYPES.get(stored.extension, DEFAULT_CONTENT_TYPE),
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

@router.get("/{material_id}", response_model=MaterialOut)
async def get_material(
    material_id: UUID,
    principal: CurrentUser,
    db: DbSession,
) -> MaterialOut:
    raise not_implemented("BBIS", "Phase 2")
    return MaterialOut.model_validate(material, from_attributes=True)


@router.get("/{material_id}/questions", response_model=Page[QuestionOut])
async def list_questions(
    material_id: UUID,
    principal: CurrentUser,
    db: DbSession,
    page: Paginated,
) -> Page[QuestionOut]:
    raise not_implemented("AI 1", "Phase 2")


@router.patch(
    "/{material_id}/questions/{question_id}",
    response_model=QuestionOut,
)
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


@router.post(
    "/{material_id}/questions:bulk",
    response_model=list[QuestionOut],
)
async def bulk_review_questions(
    material_id: UUID,
    payload: QuestionBulkReviewRequest,
    principal: CurrentUser,
    db: DbSession,
) -> list[QuestionOut]:
    """Backs the 'approve all' and 'stage N questions' actions."""
    raise not_implemented("Cyber 2", "Phase 2")
