"""Who attended each class, for the course's lecturers and admins."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AttendanceSource = Literal["clip", "teams"]


class AttendanceRow(BaseModel):
    student_id: UUID
    name: str
    email: str
    present: bool
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    minutes: int | None = Field(
        default=None, description="From first seen to last seen, rounded down. None if absent."
    )
    sources: list[AttendanceSource] = Field(
        default_factory=list,
        description="clip: joined the class in C.L.I.P. teams: seen joining the Teams meeting.",
    )


class SessionAttendanceOut(BaseModel):
    session_id: UUID
    title: str
    course_code: str
    starts_at: datetime | None
    present: int
    total: int
    students: list[AttendanceRow]


class AttendanceClass(BaseModel):
    session_id: UUID
    title: str
    starts_at: datetime | None


class CourseAttendanceRow(BaseModel):
    student_id: UUID
    name: str
    email: str
    attended: int
    classes: list[bool] = Field(description="One per class, in the order of `classes`.")


class CourseAttendanceOut(BaseModel):
    course_code: str
    classes: list[AttendanceClass] = Field(description="Finished classes, oldest first.")
    students: list[CourseAttendanceRow]
