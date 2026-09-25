"""What a Teams meeting tells C.L.I.P, from the bot or the mock adapter."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

# Teams meeting IDs are opaque strings; this bounds them without assuming a shape.
MAX_MEETING_ID_LENGTH = 256


class MeetingEventKind(StrEnum):
    STARTED = "started"
    ENDED = "ended"


class MeetingEventIn(BaseModel):
    """A meeting started or ended. Teams can deliver an event more than once,
    so one that finds the session already in that state changes nothing."""

    kind: MeetingEventKind
    meeting_id: str = Field(min_length=1, max_length=MAX_MEETING_ID_LENGTH)
    course_code: str | None = Field(
        default=None,
        description="Creates a session for a meeting that starts with none linked. "
        "Ignored once the meeting has a session.",
    )
    title: str | None = Field(
        default=None, description="The created session's title. Defaults to 'Teams meeting'."
    )


class MeetingLinkRequest(BaseModel):
    session_id: UUID
