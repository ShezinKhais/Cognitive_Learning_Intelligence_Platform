"""Lecturer-only lesson planning; answer keys never enter student session payloads."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.content import QuestionOut

MAX_LESSON_QUESTIONS = 100


class LessonQuestionOut(QuestionOut):
    material_title: str
    source_question_id: UUID | None = None


class QuestionPlanIn(BaseModel):
    selected_only: bool
    question_ids: list[UUID] = Field(default_factory=list, max_length=MAX_LESSON_QUESTIONS)
    reviewed_confirmed: bool

    @field_validator("question_ids")
    @classmethod
    def unique_ids(cls, ids: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(ids))


class QuestionPlanOut(BaseModel):
    session_id: UUID
    selected_only: bool
    editable: bool
    items: list[LessonQuestionOut]
