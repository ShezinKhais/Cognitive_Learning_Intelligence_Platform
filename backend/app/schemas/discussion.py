from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class DiscussionWrite(BaseModel):
    occurred_at: AwareDatetime
    text: str = Field(min_length=1, max_length=2000)
    shareable_confirmed: bool

    @field_validator("text")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Write a discussion note.")
        return value


class DiscussionNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    note_id: UUID
    occurred_at: datetime
    text: str
    updated_at: datetime


class DiscussionOut(BaseModel):
    notes: list[DiscussionNoteOut]
    latest_recorded_at: datetime | None
    session_status: str
