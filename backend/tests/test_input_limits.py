"""Every free-text field a client sends has a ceiling.

None of these are injection holes, since every query binds its values. They
stop a signed-in caller storing a value no one can read, or making the server
hash, scan or echo far more than any real request needs.
"""

import pytest
from pydantic import ValidationError

from app.schemas.content import (
    MAX_OPTION_CHARS,
    MAX_OPTIONS,
    MAX_PROMPT_CHARS,
    QuestionReviewRequest,
)
from app.schemas.identity import MAX_PASSWORD_LENGTH
from app.schemas.meetings import MeetingEventIn
from app.schemas.session import MAX_COURSE_CODE_LENGTH, MAX_TITLE_LENGTH


def test_a_question_edit_at_the_limits_is_accepted() -> None:
    QuestionReviewRequest(
        status="approved",
        prompt="x" * MAX_PROMPT_CHARS,
        options=["o" * MAX_OPTION_CHARS] * MAX_OPTIONS,
        correct_option=MAX_OPTIONS - 1,
    )


@pytest.mark.parametrize(
    "edit",
    [
        {"prompt": "x" * (MAX_PROMPT_CHARS + 1)},
        {"options": ["o" * (MAX_OPTION_CHARS + 1), "b"]},
        {"options": ["o"] * (MAX_OPTIONS + 1)},
        {"correct_option": -1},
        {"correct_option": MAX_OPTIONS},
    ],
    ids=["long prompt", "long option", "too many options", "negative key", "key past the options"],
)
def test_a_question_edit_past_the_limits_is_refused(edit: dict) -> None:
    with pytest.raises(ValidationError):
        QuestionReviewRequest(status="rejected", **edit)


@pytest.mark.parametrize(
    "field",
    [
        {"course_code": "C" * (MAX_COURSE_CODE_LENGTH + 1)},
        {"title": "t" * (MAX_TITLE_LENGTH + 1)},
    ],
    ids=["course code", "title"],
)
def test_a_meeting_event_with_an_oversized_field_is_refused(field: dict) -> None:
    with pytest.raises(ValidationError):
        MeetingEventIn(kind="started", meeting_id="m-1", **field)


def test_an_oversized_password_is_refused_before_it_is_hashed(client) -> None:  # noqa: ANN001
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "lecturer@clip.example.com", "password": "p" * (MAX_PASSWORD_LENGTH + 1)},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"course_code": "C" * (MAX_COURSE_CODE_LENGTH + 1), "title": "Week 7"},
        {"course_code": "CSIT321", "title": "t" * (MAX_TITLE_LENGTH + 1)},
    ],
    ids=["course code", "title"],
)
def test_a_session_with_an_oversized_field_is_refused(as_lecturer, body: dict) -> None:  # noqa: ANN001
    assert as_lecturer.post("/api/v1/sessions", json=body).status_code == 422


def test_a_page_offset_past_the_ceiling_is_refused(as_lecturer) -> None:  # noqa: ANN001
    assert as_lecturer.get("/api/v1/sessions", params={"offset": 100_001}).status_code == 422
