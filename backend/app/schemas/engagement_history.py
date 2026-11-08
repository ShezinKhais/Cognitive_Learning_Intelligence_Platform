"""Engagement across a term: one row per finished class, and the students who
have gone quiet over several of them.

Owner: General CS. Built from what C.L.I.P already keeps after a class (who
joined, the checkpoints, the answers, and the attention summaries of students
who turned the indicators on), not from a new record.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SessionEngagement(BaseModel):
    session_id: UUID
    title: str
    course_code: str
    held_at: datetime
    present: int = Field(description="Students who joined.")
    checkpoints: int
    answer_rate: float | None = Field(
        description="Answers over the answers that were possible, 0 to 1. None with no checkpoints."
    )
    correct_rate: float | None = Field(
        description="Of the answers that could be marked, the share that were right."
    )
    on_screen: float | None = Field(
        description=(
            "Average share of time looking at the screen, from students who turned the "
            "indicator on. None unless at least three did, so no one student can be read off it."
        )
    )


class QuietStudent(BaseModel):
    student_id: UUID
    name: str
    course_code: str
    sessions_considered: int = Field(description="Recent classes of their course looked at.")
    sessions_missed: int = Field(description="Of those, how many they did not join.")
    answer_rate: float | None = Field(
        description="Their answers over the checkpoints of the classes they joined."
    )


class EngagementHistory(BaseModel):
    sessions: list[SessionEngagement]
    quiet: list[QuietStudent] = Field(
        description=(
            "Students who missed most of the recent classes or answered few checkpoints in "
            "them. Students with an approved special consideration are never listed."
        )
    )
    recent_window: int = Field(description="How many recent classes the quiet list looks at.")
