"""Additive AI2 post-session review contract; no model-generated claims."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.session import ComprehensionLabel


class ReviewSession(BaseModel):
    id: UUID
    title: str
    course_code: str
    ended_at: datetime | None


class ReviewAnswer(BaseModel):
    id: UUID
    question: str
    topic: str | None
    answer: str
    is_correct: bool | None
    label: ComprehensionLabel | None
    confidence: float | None = Field(ge=0, le=1)
    submitted_at: datetime


class ReviewEngagement(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    score: None = None
    explanation: str = (
        "A verified post-session engagement record with confidence and signal availability "
        "is not available. Missing readings are not zero and do not indicate understanding."
    )


class StudentReview(BaseModel):
    session: ReviewSession
    questions_attempted: int
    questions_missed: int
    engagement: ReviewEngagement = Field(default_factory=ReviewEngagement)
    answers: list[ReviewAnswer]
    total: int
    limit: int
    offset: int


class ReviewSource(BaseModel):
    chunk_id: UUID
    material_title: str
    source_page: int | None
    text: str
    match: Literal["excerpt", "page"]


class ReviewSources(BaseModel):
    items: list[ReviewSource]
    has_more: bool = False
