"""Live session, response and analytics contracts.

Owners: session lifecycle and delivery — General CS. Persistence — BBIS.
Scoring — Cyber 1. Classification — AI 1.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class SessionStatus(StrEnum):
    PREPARED = "prepared"
    ACTIVE = "active"
    ENDING = "ending"
    ENDED = "ended"
    CANCELLED = "cancelled"


class ComprehensionLabel(StrEnum):
    """Design document labels. The SRS's Clear/Partial/Misunderstood is stale."""

    MASTERED = "mastered"
    PARTIAL = "partial"
    STRUGGLING = "struggling"


class EngagementStatus(StrEnum):
    ENGAGED = "engaged"
    AT_RISK = "at_risk"
    DISENGAGED = "disengaged"
    INSUFFICIENT_DATA = "insufficient_data"


class SessionOut(BaseModel):
    id: UUID
    course_code: str
    title: str
    lecturer_id: UUID
    status: SessionStatus
    starts_at: datetime | None = None
    ended_at: datetime | None = None
    teams_meeting_id: str | None = None
    participant_count: int = 0
    questions_delivered: int = 0


class SessionCreateRequest(BaseModel):
    course_code: str
    title: str
    starts_at: datetime | None = None


class ResponseOut(BaseModel):
    id: UUID
    question_id: UUID
    student_id: UUID
    selected_option: int | None = None
    free_text: str | None = None
    is_correct: bool | None = None
    elapsed_ms: int | None = None
    submitted_at: datetime


class ComprehensionOut(BaseModel):
    response_id: UUID
    label: ComprehensionLabel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class EngagementOut(BaseModel):
    """Engagement and comprehension are reported separately and must not be
    combined into a single figure anywhere in the API."""

    student_id: UUID
    session_id: UUID
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: EngagementStatus
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Low confidence renders as 'insufficient data', never as 'disengaged'.",
    )
    signals_available: list[str] = Field(
        default_factory=list,
        description="Which signals contributed. Missing signals are renormalised, not zeroed.",
    )
    computed_at: datetime


class StudentSessionSummary(BaseModel):
    student_id: UUID
    session_id: UUID
    questions_attempted: int
    questions_missed: int
    engagement: EngagementOut
    comprehension_by_topic: dict[str, ComprehensionLabel] = Field(default_factory=dict)


class ClassComprehensionAlert(BaseModel):
    session_id: UUID
    question_id: UUID
    topic: str | None
    correct_ratio: float = Field(ge=0.0, le=1.0)
    respondents: int
    threshold: float
    raised_at: datetime
