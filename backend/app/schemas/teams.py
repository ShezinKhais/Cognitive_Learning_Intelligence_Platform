"""Teams meeting-event contract.

Owners: General CS (event handling), BBIS (roster/mapping persistence),
Cyber 1 (signature verification). New in Phase 4 -- Phase 1's frozen
contract predates Teams integration, so this is additive rather than a
change to anything already relied on.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

MAX_PARTICIPANTS_PER_EVENT = 500


class TeamsEventType(StrEnum):
    MEETING_STARTED = "meeting.started"
    MEETING_ENDED = "meeting.ended"


class TeamsParticipant(BaseModel):
    teams_user_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None


class TeamsMeetingEventRequest(BaseModel):
    event: TeamsEventType
    teams_meeting_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    course_code: str = Field(min_length=1, max_length=20)
    title: str = Field(default="Live Session", max_length=255)
    organizer_teams_user_id: str = Field(min_length=1, max_length=255)
    organizer_email: EmailStr | None = None
    participants: list[TeamsParticipant] = Field(
        default_factory=list, max_length=MAX_PARTICIPANTS_PER_EVENT
    )


class RosterSyncSummary(BaseModel):
    matched: int = 0
    unmatched: int = 0
    duplicates: int = 0
    unmatched_names: list[str] = Field(default_factory=list)


class TeamsMeetingEventResult(BaseModel):
    status: str  # "started" | "blocked" | "ended" | "ignored"
    session_id: UUID | None = None
    reason: str | None = None
    roster: RosterSyncSummary | None = None
