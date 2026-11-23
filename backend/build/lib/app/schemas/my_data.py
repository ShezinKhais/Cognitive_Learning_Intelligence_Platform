"""Request and response shapes for a student's own-data routes.

Owner: BBIS, Phase 7. Part of the frozen contract once merged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StudentDataExport(BaseModel):
    generated_at: datetime
    retention_days: int = Field(description="Session data is deleted this many days after it ends.")
    account: dict[str, Any]
    profile: dict[str, Any]
    answers: list[dict[str, Any]]
    prompts: list[dict[str, Any]]
    engagement: list[dict[str, Any]]
    attention_summaries: list[dict[str, Any]]
    missed_responses: list[dict[str, Any]]
    deletion_requests: list[dict[str, Any]]
    history: list[dict[str, Any]] = Field(
        description="Summaries kept per course and semester after session data is deleted."
    )


class MyDeletionRequestCreate(BaseModel):
    confirm: bool = Field(
        description=(
            "Must be true: the student was told this erases their data and cannot be undone."
        )
    )
    reason: str | None = Field(
        default=None, max_length=500, description="Why, in a few words. Optional."
    )


class MyDeletionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: UUID
    status: str = Field(description="requested, approved, rejected or executed.")
    requested_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None
