"""Account management by an administrator.

Owner: General CS. Accounts are the database users production signs in
with. A Teams single sign-on finds an account by its email and never creates
one, so this is where an organisation's people are added.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.identity import Role

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str


class CourseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)

    @field_validator("code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class AccountOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: Role
    active: bool
    course: CourseOut | None = Field(description="The student's course. Staff have none.")
    has_password: bool = Field(description="Can sign in on the website, not only through Teams.")
    teams_linked: bool = Field(description="Has signed in through Teams at least once.")


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255, pattern=EMAIL_PATTERN)
    role: Role
    course_id: UUID | None = Field(default=None, description="Required for a student.")
    website_password: bool = Field(
        default=False,
        description=(
            "Issue a password for the website. Students in Teams do not need one; "
            "staff do, to reach the dashboards."
        ),
    )

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("A name is required.")
        return stripped


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = Field(
        default=None, description="Lecturer and admin can swap. A student stays a student."
    )
    active: bool | None = None
    course_id: UUID | None = Field(default=None, description="Move a student to this course.")


class AccountIssued(BaseModel):
    """An account and, when one was issued, its password. The password is
    shown this once and kept only as a hash."""

    account: AccountOut
    password: str | None = None
