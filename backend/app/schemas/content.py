"""Lecture material and question contracts.

Owners: extraction and generation (AI 1). Review interface (Cyber 2).
Persistence (BBIS).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


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


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


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

    status: QuestionStatus
    prompt: str | None = None
    options: list[str] | None = None
    correct_option: int | None = None
    difficulty: Difficulty | None = None


class QuestionBulkReviewRequest(BaseModel):
    question_ids: list[UUID]
    status: QuestionStatus
