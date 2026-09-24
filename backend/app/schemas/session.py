"""Live session, response and analytics contracts.

Owners: session lifecycle and delivery (General CS). Persistence (BBIS).
Scoring (Cyber 1). Classification (AI 1)."""

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


class ReadinessIssueCode(StrEnum):
    """Why a session is not ready to start, or what the lecturer should know.

    The first three block the start. MATERIAL_FAILED is only a warning: one
    broken upload should not hold back a class whose other material is fine.
    """

    NO_MATERIAL = "no_material"
    MATERIAL_PROCESSING = "material_processing"
    NO_APPROVED_QUESTIONS = "no_approved_questions"
    MATERIAL_FAILED = "material_failed"


class SessionOut(BaseModel):
    id: UUID
    course_code: str
    title: str
    lecturer_id: UUID
    status: SessionStatus
    starts_at: datetime | None = None
    ended_at: datetime | None = None
    teams_meeting_id: str | None = None
    participant_count: int = Field(
        default=0, description="Students connected now, each counted once."
    )
    questions_delivered: int = 0
    paused: bool = Field(
        default=False,
        description="An active session the lecturer has paused. No question goes out until "
        "it resumes.",
    )


class SessionCreateRequest(BaseModel):
    course_code: str
    title: str
    starts_at: datetime | None = None


class DeliverableQuestionOut(BaseModel):
    """A staged question the current live session may deliver."""

    id: UUID
    material_id: UUID
    prompt: str
    options: list[str] | None = None
    source_slide: int | None = None


class ReadinessIssue(BaseModel):
    """One reason a session cannot start yet, or one thing worth a warning."""

    code: ReadinessIssueCode
    message: str = Field(description="Plain-language explanation for the lecturer.")
    material_id: UUID | None = Field(
        default=None,
        description="The material this is about, when it is about one.",
    )


class SessionReadinessOut(BaseModel):
    """Whether a prepared session has the content it needs to begin.

    start_session runs the same check, so a session this reports as ready
    will not be refused for content, and one it reports as not ready will be.
    """

    session_id: UUID
    ready: bool = Field(description="True only when blockers is empty.")
    blockers: list[ReadinessIssue] = Field(
        default_factory=list,
        description="Each one stops the session from starting.",
    )
    warnings: list[ReadinessIssue] = Field(
        default_factory=list,
        description="Worth showing the lecturer, but they do not stop the start.",
    )
    materials_total: int = 0
    materials_processing: int = Field(default=0, description="Pending or still being processed.")
    materials_failed: int = 0
    deliverable_questions: int = Field(
        default=0, description="Approved, staged questions this session may deliver."
    )
    checked_at: datetime


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
