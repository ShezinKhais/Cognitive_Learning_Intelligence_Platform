"""A student's own engagement history across their finished classes (#243).

The contract, agreed in docs/student-engagement-history.md: per class, facts
that were stored, each with whether it was available. There is no score.
Engagement is kept apart from comprehension, and a reading that was not
taken is reported as unavailable, never as zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReadingAvailability = Literal["available", "none_recorded", "not_consented"]


class ClassParticipation(BaseModel):
    joined: bool = Field(description="The student connected to the class at least once.")
    checkpoints: int = Field(description="Checkpoints sent to the class.")
    answered: int
    missed: int = Field(description="Sent while connected, closed without an answer.")


class ClassReadings(BaseModel):
    """Whether optional device readings exist for this class. Counts of
    one-minute windows, not a measure of attention or understanding."""

    camera: ReadingAvailability
    camera_windows: int | None = Field(default=None, ge=1)
    microphone: ReadingAvailability
    microphone_windows: int | None = Field(default=None, ge=1)


class ClassEngagement(BaseModel):
    session_id: UUID
    title: str
    course_code: str
    ended_at: datetime | None
    participation: ClassParticipation
    readings: ClassReadings


class StudentEngagementHistory(BaseModel):
    classes: list[ClassEngagement]
    total: int
    limit: int
    offset: int
    explanation: str = (
        "What was recorded in each finished class. Answers and missed checkpoints come from "
        "the class itself. Camera and microphone counts appear only for readings you agreed "
        "to, and only from when you agreed. A class with no reading says so; it is not counted "
        "as zero, and none of this measures how well you understood."
    )
