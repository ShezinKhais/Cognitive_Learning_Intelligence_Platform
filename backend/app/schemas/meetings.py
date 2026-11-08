"""What a Teams meeting tells C.L.I.P, from the bot or the mock adapter."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.accounts import CourseOut
from app.schemas.session import MAX_COURSE_CODE_LENGTH, MAX_TITLE_LENGTH

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
        max_length=MAX_COURSE_CODE_LENGTH,
        description="Creates a session for a meeting that starts with none linked. "
        "Ignored once the meeting has a session.",
    )
    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE_LENGTH,
        description="The created session's title. Defaults to 'Teams meeting'.",
    )


class MeetingLinkRequest(BaseModel):
    session_id: UUID


class TeamsActivity(BaseModel):
    """The part of a Bot Framework activity the bot reads. The rest of what
    Teams sends is accepted and ignored."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: str
    name: str | None = None
    service_url: str = Field(alias="serviceUrl")
    channel_id: str | None = Field(
        default=None,
        alias="channelId",
        description="The Bot Framework channel. Only 'msteams' is acted on.",
    )
    channel_data: dict[str, Any] | None = Field(default=None, alias="channelData")


def activity_meeting_id(activity: TeamsActivity) -> str | None:
    """Read a meeting identity after the caller authenticates the bot activity.

    Meeting lifecycle events can carry value.Id without channelData.meeting.
    Never interpret an arbitrary message or installation value as a meeting ID.
    Conflicting identities are refused rather than linking two different meetings.
    """
    meeting = (activity.channel_data or {}).get("meeting")
    channel_id = meeting.get("id") if isinstance(meeting, dict) else None
    value_id = None
    if activity.type == "event" and activity.name in {
        "application/vnd.microsoft.meetingStart",
        "application/vnd.microsoft.meetingEnd",
    }:
        value = (activity.model_extra or {}).get("value")
        value_id = value.get("Id") if isinstance(value, dict) else None
    candidates = [candidate for candidate in (channel_id, value_id) if candidate is not None]
    if not candidates or any(
        not isinstance(candidate, str)
        or not candidate.strip()
        or len(candidate) > MAX_MEETING_ID_LENGTH
        for candidate in candidates
    ):
        return None
    return candidates[0] if all(candidate == candidates[0] for candidate in candidates) else None


class MeetingClassSuggestion(BaseModel):
    """What the side panel offers for a meeting with no session: the course
    and title guessed from the meeting's title, and the lecturer's courses
    to choose from instead."""

    meeting_title: str | None = Field(description="The title Teams gives the meeting, if known.")
    course_code: str | None = Field(description="The course guessed for this class.")
    title: str
    courses: list[CourseOut]


class MeetingClassStart(BaseModel):
    course_code: str = Field(min_length=1, max_length=MAX_COURSE_CODE_LENGTH)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
