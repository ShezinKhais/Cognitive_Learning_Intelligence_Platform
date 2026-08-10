"""Identity, consent and administration contracts.

Owners: authentication and RBAC (Cyber 1). Administrator console (Cyber 2).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class Role(StrEnum):
    STUDENT = "student"
    LECTURER = "lecturer"
    ADMIN = "admin"


class ConsentType(StrEnum):
    """Granular. Declining one must never block the others, and declining
    camera or microphone must never lower an engagement score."""

    TERMS = "terms"
    ENGAGEMENT_MONITORING = "engagement_monitoring"
    CAMERA = "camera"
    MICROPHONE = "microphone"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    role: Role


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: Role
    consents: list[ConsentType] = Field(default_factory=list)


class ConsentRequest(BaseModel):
    consent_type: ConsentType
    granted: bool


class ConsentOut(BaseModel):
    consent_type: ConsentType
    granted: bool
    recorded_at: datetime


class TimetableImportResult(BaseModel):
    """Result of an administrator uploading a timetable CSV or XLSX.

    CSV and XLSX are parsed as structured data. There is no OCR path, because a
    misread digit would silently assign a student to the wrong session.
    """

    rows_read: int
    sessions_created: int
    conflicts: list[str] = Field(default_factory=list)
    unmatched_lecturers: list[str] = Field(default_factory=list)
    unmatched_students: list[str] = Field(default_factory=list)
