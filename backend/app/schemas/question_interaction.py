"""Authoring and public delivery shapes for matching and ordering checkpoints."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator

Item = Annotated[str, Field(min_length=1, max_length=180)]
Index = Annotated[StrictInt, Field(ge=0, lt=8)]


class InteractionInput(BaseModel):
    """Choices in solution order. Matching has one label per choice."""

    labels: list[Item] = Field(default_factory=list, max_length=8)
    choices: list[Item] = Field(min_length=2, max_length=8)

    @field_validator("labels", "choices")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        items = [value.strip() for value in values]
        if any(not item or len(item.splitlines()) != 1 for item in items):
            raise ValueError("Use one non-blank item per entry.")
        if len({item.casefold() for item in items}) != len(items):
            raise ValueError("Items must be distinct.")
        return items


class PublicInteraction(InteractionInput):
    kind: Literal["matching", "ordering"]


class QuestionInteraction(PublicInteraction):
    correct_order: list[Index] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def check_key(self) -> "QuestionInteraction":
        if sorted(self.correct_order) != list(range(len(self.choices))):
            raise ValueError("The answer key must use each choice once.")
        if self.kind == "matching" and len(self.labels) != len(self.choices):
            raise ValueError("Matching needs one label for each choice.")
        if self.kind == "ordering" and self.labels:
            raise ValueError("Ordering has choices only.")
        return self
