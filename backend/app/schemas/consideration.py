"""Special consideration requests: what a student asks for, and the decision.

Owner: General CS, Phase 8. The fact of an accommodation is what the live
class acts on (app.realtime.accommodations); the request's details and note
are for administrators only and never reach a lecturer.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MAX_NOTE = 500
MAX_DECISION_NOTE = 300


class ConsiderationNeed(StrEnum):
    CAMERA = "camera"  # cannot use a camera in class
    GAZE = "gaze"  # eye-tracking does not work for them
    PACE = "pace"  # needs more time to answer
    PROMPTS = "prompts"  # check-in prompts disrupt them


ConsiderationStatus = Literal["pending", "approved", "rejected", "withdrawn"]


class ConsiderationCreate(BaseModel):
    needs: list[ConsiderationNeed] = Field(min_length=1, max_length=len(ConsiderationNeed))
    until: date | None = Field(default=None, description="Last day it applies; null for the term.")
    note: str | None = Field(default=None, max_length=MAX_NOTE)

    @field_validator("needs")
    @classmethod
    def _once_each(cls, needs: list[ConsiderationNeed]) -> list[ConsiderationNeed]:
        return list(dict.fromkeys(needs))

    @field_validator("note")
    @classmethod
    def _blank_is_none(cls, note: str | None) -> str | None:
        return note.strip() or None if note is not None else None


class ConsiderationOut(BaseModel):
    id: UUID
    needs: list[ConsiderationNeed]
    until: date | None
    note: str | None
    status: ConsiderationStatus
    created_at: datetime
    reviewed_at: datetime | None
    decision_note: str | None


class MyConsiderationOut(BaseModel):
    """The student's most recent request, if any."""

    current: ConsiderationOut | None


class ConsiderationAdminOut(ConsiderationOut):
    student_name: str
    student_email: str
    course_code: str


class ConsiderationDecision(BaseModel):
    note: str | None = Field(default=None, max_length=MAX_DECISION_NOTE)
