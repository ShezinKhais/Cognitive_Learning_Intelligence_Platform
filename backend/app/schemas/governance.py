"""Request and response shapes for the governance routes.

Owner: BBIS, Phase 7. Part of the frozen contract once merged: a change to a
field here is a version bump, not a tweak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DeletionRequestCreate(BaseModel):
    target_type: Literal["session", "student"]
    target_id: UUID
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Why, in a few words. Never personal content.",
    )


class DeletionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: UUID
    target_type: str
    target_id: UUID
    status: str = Field(description="requested, approved, rejected or executed.")
    reason: str | None
    requested_by: UUID
    requested_at: datetime
    decided_by: UUID | None
    decided_at: datetime | None
    executed_by: UUID | None
    executed_at: datetime | None
    outcome: dict[str, Any] | None = Field(description="What was deleted, as counts only.")


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: UUID
    user_id: UUID | None = Field(description="None for something the system did on its own.")
    action_type: str
    timestamp: datetime
    ip_address: str | None
    target_type: str | None
    target_id: UUID | None
    details: dict[str, Any] | None = Field(description="Counts and identifiers, never content.")


class RetentionReportOut(BaseModel):
    cutoff: datetime = Field(description="Data from sessions older than this is purged.")
    dry_run: bool
    retention_days: int
    sessions: int
    answers: int
    roster_syncs: int


class RetentionRunRequest(BaseModel):
    confirm: Literal[True] = Field(description="Must be true. A purge cannot be undone.")
