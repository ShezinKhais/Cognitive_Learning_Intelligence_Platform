"""Lecture material and question contracts.

Owners: extraction and generation (AI 1). Review interface (Cyber 2).
Persistence (BBIS).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class MaterialStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QuestionType(StrEnum):
    MCQ = "mcq"
    FREE_TEXT = "free_text"


class QuestionStatus(StrEnum):
    """The human-in-the-loop review workflow. A question is only ever delivered
    to students from the STAGED state, so nothing reaches a class without a
    lecturer approving it."""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    STAGED = "staged"
    DELIVERED = "delivered"


class ReviewDecision(StrEnum):
    """The statuses a lecturer may set through the review routes.

    Every QuestionStatus except DELIVERED. A question becomes delivered when
    the session actually sends it to students; set by hand, it would freeze a
    question as "already asked" when no student ever saw it.
    """

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    STAGED = "staged"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class MaterialPageOut(BaseModel):
    """Extracted text and quality indicators for one source page or slide."""

    page_number: int = Field(ge=1)
    text: str
    word_count: int | None = Field(default=None, ge=0)
    visual_element_count: int | None = Field(default=None, ge=0)
    is_thin: bool = False
    is_visual_heavy: bool = False


class MaterialOut(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: MaterialStatus
    page_count: int | None = None
    chunk_count: int | None = None
    error: str | None = None
    uploaded_at: datetime
    warnings: list[str] = Field(default_factory=list)
    pages: list[MaterialPageOut] = Field(default_factory=list)


class QuestionOut(BaseModel):
    id: UUID
    material_id: UUID
    type: QuestionType
    status: QuestionStatus
    difficulty: Difficulty
    prompt: str
    options: list[str] | None = None
    correct_option: int | None = Field(
        default=None,
        description="Never sent to students. Lecturer and admin views only.",
    )
    topic: str | None = None
    source_slide: int | None = Field(
        default=None,
        description="Drives the 'see slide 3' reference in student feedback.",
    )
    source_excerpt: str | None = Field(
        default=None,
        description="The text the question was generated from. Grounding evidence.",
    )


class QuestionReviewRequest(BaseModel):
    """A lecturer approving, editing or rejecting a generated question."""

    status: ReviewDecision
    prompt: str | None = None
    options: list[str] | None = None
    correct_option: int | None = None
    difficulty: Difficulty | None = None
    # Phase 3: which live session this question is being staged for. A
    # question generated at upload has no session yet (see app.models.
    # question), so staging is the one review action that has to name one.
    # Required by QuestionRepository.apply_review only when status is
    # "staged" and the question does not already carry a session_id.
    session_id: UUID | None = None


# Far above any one material's question count. Unbounded, a single request
# could name enough ids to make the lookup query itself the problem.
MAX_BULK_REVIEW_IDS = 500


class QuestionBulkReviewRequest(BaseModel):
    question_ids: list[UUID] = Field(max_length=MAX_BULK_REVIEW_IDS)
    status: ReviewDecision
    # Same meaning as QuestionReviewRequest.session_id, applied to every
    # question in the batch -- "stage these N questions for this session".
    session_id: UUID | None = None

    @field_validator("question_ids")
    @classmethod
    def _once_each(cls, ids: list[UUID]) -> list[UUID]:
        # A repeated id was reviewed twice and listed twice in the result.
        return list(dict.fromkeys(ids))


class QuestionBulkReviewResult(BaseModel):
    """Response for the bulk review endpoint.

    Separate from a bare list[QuestionOut] so a lecturer can tell "all N
    approved" from "N approved, M skipped" -- a bulk action that silently
    drops ids a lecturer expected to be included looks identical to success
    unless the skipped ones are reported back.
    """

    updated: list[QuestionOut]
    skipped_ids: list[UUID]
