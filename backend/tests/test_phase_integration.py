"""Session discovery, authorization, live delivery, scoring and room activity
through the actual REST/WebSocket routes and PostgreSQL stores.

Material generation/model quality and a real Teams tenant are separate checks.
"""

from uuid import UUID

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.realtime.classroom import classroom
from app.schemas.identity import ConsentType, Role

from .dev_credentials import STUDENT_PASSWORD
from .session_support import (
    add_course,
    add_question,
    create_session,
    enrol,
    sign_in_as,
    token_for,
)


async def test_discover_join_answer_and_read_the_same_persisted_session(db, app) -> None:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    question_id = await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course, "Cross-phase integration")
    session_id = session["id"]
    assert client.post(f"/api/v1/sessions/{session_id}/start").status_code == 200
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD, ConsentType)
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    listing = client.get("/api/v1/sessions")
    assert listing.status_code == 200
    assert session_id in {row["id"] for row in listing.json()["items"]}
    detail = client.get(f"/api/v1/sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "active"
    # A student who can discover a class must not inherit the lecturer's controls.
    assert client.post(f"/api/v1/sessions/{session_id}/pause").status_code == 403

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session_id}})
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json()["type"] == "session.state"
        ws.send_json({"type": "room.confirm", "data": {"room_label": "Integration room"}})
        ws.send_json({"type": "ping", "data": {}})
        assert ws.receive_json()["type"] == "pong"
        sign_in_as(app, LECTURER_ID, Role.LECTURER)
        delivered = client.post(f"/api/v1/sessions/{session_id}/questions/{question_id}:deliver")
        assert delivered.status_code == 202
        assert ws.receive_json()["type"] == "question.delivered"
        ws.send_json(
            {
                "type": "answer.submit",
                "data": {
                    "question_id": str(question_id),
                    "selected_option": 1,
                    "client_elapsed_ms": 800,
                },
            }
        )
        receipt = ws.receive_json()
        assert receipt["type"] == "answer.receipt"
        assert receipt["data"]["accepted"] is True
        feedback = ws.receive_json()
        assert feedback["type"] == "feedback.result"
        assert feedback["data"]["correct"] is True
        [room] = classroom.rooms(UUID(session_id))
        assert room.room_label == "Integration room" and room.task_interactions == 1
        sign_in_as(app, STUDENT_ID, Role.STUDENT)
        responses = client.get(f"/api/v1/sessions/{session_id}/responses")
        assert responses.status_code == 200
        assert responses.json()["total"] == 1
        assert responses.json()["items"][0]["question_id"] == str(question_id)
        sign_in_as(app, LECTURER_ID, Role.LECTURER)
        assert client.post(f"/api/v1/sessions/{session_id}/end").status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.get(f"/api/v1/sessions/{session_id}").json()["status"] == "ended"
    # Phase 7 must read the same answer saved through the live socket, not just
    # independently seeded review fixtures. Both review contracts agree on counts.
    reviews = client.get("/api/v1/student-reviews")
    assert reviews.status_code == 200
    assert session_id in {row["id"] for row in reviews.json()["items"]}
    review = client.get(f"/api/v1/student-reviews/{session_id}")
    assert review.status_code == 200
    assert review.headers["cache-control"] == "no-store"
    assert review.json()["questions_attempted"] == 1
    assert review.json()["questions_missed"] == 0
    assert review.json()["answers"][0]["is_correct"] is True
    student_id = responses.json()["items"][0]["student_id"]
    summary = client.get(f"/api/v1/sessions/{session_id}/summary/{student_id}")
    assert summary.status_code == 200
    assert summary.json()["questions_attempted"] == review.json()["questions_attempted"]
    assert summary.json()["questions_missed"] == review.json()["questions_missed"]
    assert summary.json()["engagement"]["score"] is None
