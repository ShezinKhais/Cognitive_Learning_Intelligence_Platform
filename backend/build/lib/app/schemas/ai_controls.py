"""Reading and saving the lecturer's AI switches for a class."""

from __future__ import annotations

from pydantic import Field

from app.schemas.events import AiControls


class AiControlsOut(AiControls):
    course_defaults: AiControls = Field(
        description="What every new class of this course starts with."
    )


class AiControlsUpdate(AiControls):
    apply_to_course: bool = Field(
        default=False,
        description="Also make these the course's defaults for every new class. Only a "
        "lecturer of the course, or an admin, may.",
    )
