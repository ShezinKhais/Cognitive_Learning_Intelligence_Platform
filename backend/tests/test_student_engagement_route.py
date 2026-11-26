"""Student engagement history API authorization and response tests."""

from unittest.mock import AsyncMock

from app.api.deps import get_db
from app.auth.store import STUDENT_ID
from app.schemas.student_engagement import StudentEngagementHistory
from app.services import student_engagement


def test_student_history_route_uses_authenticated_identity(as_student, app, monkeypatch):
    async def db_override():
        yield object()

    app.dependency_overrides[get_db] = db_override

    result = StudentEngagementHistory(
        classes=[],
        total=0,
        limit=20,
        offset=0,
    )

    history = AsyncMock(return_value=result)
    monkeypatch.setattr(student_engagement, "history", history)

    response = as_student.get("/api/v1/me/engagement-history?limit=20&offset=0")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"

    history.assert_awaited_once()
    assert history.await_args.args[1:] == (STUDENT_ID, 20, 0)


def test_lecturer_cannot_read_student_engagement_history(as_lecturer):
    response = as_lecturer.get("/api/v1/me/engagement-history")
    assert response.status_code == 403


def test_anonymous_user_cannot_read_student_engagement_history(client):
    response = client.get("/api/v1/me/engagement-history")
    assert response.status_code == 401


def test_empty_student_engagement_history_is_explicit(as_student, app, monkeypatch):
    async def db_override():
        yield object()

    app.dependency_overrides[get_db] = db_override

    history = AsyncMock(
        return_value=StudentEngagementHistory(
            classes=[],
            total=0,
            limit=20,
            offset=0,
        )
    )

    monkeypatch.setattr(student_engagement, "history", history)

    response = as_student.get("/api/v1/me/engagement-history")

    assert response.status_code == 200

    body = response.json()

    assert body["classes"] == []
    assert body["total"] == 0
    assert body["explanation"] == (
        "What was recorded in each finished class. Answers and missed checkpoints come from "
        "the class itself. Camera and microphone counts appear only for readings you agreed "
        "to, and only from when you agreed. A class with no reading says so; it is not counted "
        "as zero, and none of this measures how well you understood."
    )
