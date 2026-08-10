"""Identity, consent and administration contracts.

Owners: authentication and RBAC (Cyber 1). Administrator console (Cyber 2).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class Role(StrEnum):
    STUDENT = "student"
    LECTURER = "lecturer"
    ADMIN = "admin"


class ConsentType(StrEnum):
    """Independent consent choices.

    Declining one consent must never automatically block another.
    Declining camera or microphone consent must never lower an
    engagement score.
    """

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
    """One consent decision.

    Kept for backwards compatibility with the existing
    POST /auth/consent endpoint.
    """

    consent_type: ConsentType
    granted: bool


class ConsentOut(BaseModel):
    consent_type: ConsentType
    granted: bool
    recorded_at: datetime


class ConsentBatchRequest(BaseModel):
    """A group of consent decisions saved as one operation."""

    consents: list[ConsentRequest] = Field(
        min_length=1,
        max_length=len(ConsentType),
    )

    @model_validator(mode="after")
    def reject_duplicate_consent_types(
        self,
    ) -> ConsentBatchRequest:
        consent_types = [consent.consent_type for consent in self.consents]

        if len(consent_types) != len(set(consent_types)):
            raise ValueError("Each consent type may appear only once.")

        return self


class ConsentBatchOut(BaseModel):
    consents: list[ConsentOut]


class TimetableImportResult(BaseModel):
    """Result of an administrator uploading a timetable CSV or XLSX.

    CSV and XLSX are parsed as structured data. There is no OCR path,
    because a misread digit could silently assign a student to the
    wrong session.
    """

    rows_read: int
    sessions_created: int
    conflicts: list[str] = Field(default_factory=list)
    unmatched_lecturers: list[str] = Field(default_factory=list)
    unmatched_students: list[str] = Field(default_factory=list)
