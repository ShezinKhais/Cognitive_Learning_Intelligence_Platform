"""Lecturers asking for new courses, and an admin's decision."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.accounts import CourseCreate

CourseRequestStatus = Literal["pending", "approved", "declined"]


class CourseRequestCreate(CourseCreate):
    reason: str | None = Field(
        default=None, max_length=500, description="Why the course is needed, for the admin."
    )


class CourseRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    reason: str | None
    status: CourseRequestStatus
    requested_by: UUID
    requester_name: str | None = None
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


class CourseRequestApprove(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=255, description="Correct the course name first."
    )


class CourseRequestDecline(BaseModel):
    note: str | None = Field(
        default=None, max_length=500, description="Why, shown to the lecturer who asked."
    )


class CourseRename(BaseModel):
    name: str = Field(min_length=1, max_length=255)
