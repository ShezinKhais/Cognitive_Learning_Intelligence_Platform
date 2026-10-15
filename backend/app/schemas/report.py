"""Session reports: a lecturer asks for one, it is built in the background,
and it is read back as JSON or as a PDF.

Owner: General CS, Phase 7 (#65). Additive to the frozen contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.session import AlertOut, SessionStatus, TopicDifficultyOut


class ReportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class ReportParticipation(BaseModel):
    """What happened in the session, counted from what was stored."""

    students: int = Field(ge=0, description="Students who joined at least once.")
    questions_delivered: int = Field(ge=0)
    answers: int = Field(ge=0)
    missed_answers: int = Field(ge=0, description="A student shown a question who did not answer.")
    attention_prompts: int = Field(ge=0)


class SessionReport(BaseModel):
    """One session, as the lecturer's report shows it.

    Comprehension (topics) and engagement are reported apart and never
    combined into one figure, as everywhere else. Nothing here names a student.
    """

    session_id: UUID
    course_code: str
    title: str
    status: SessionStatus
    starts_at: datetime | None
    ended_at: datetime | None
    generated_at: datetime
    participation: ReportParticipation
    topics: list[TopicDifficultyOut] = Field(description="Hardest first, as /topics serves them.")
    alerts: list[AlertOut] = Field(description="Oldest first, as /alerts serves them.")


class ReportJobOut(BaseModel):
    """Where a report has got to. Poll it until status is ready or failed."""

    report_id: UUID
    session_id: UUID
    status: ReportStatus
    requested_at: datetime
    finished_at: datetime | None = None
    error: str | None = Field(
        default=None, description="Machine-readable, when failed: INTERNAL_ERROR or INTERRUPTED."
    )
    message: str | None = Field(default=None, description="For the lecturer, when failed.")
    report: SessionReport | None = Field(default=None, description="Set once status is ready.")
