"""Cyber 1, Phase 6: the join-time accommodation lookup, through the real socket."""

from __future__ import annotations

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.realtime.classroom import classroom
from app.schemas.identity import Role

from .dev_credentials import STUDENT_PASSWORD
from .session_support import (
    add_course,
    add_question,
    create_session,
    enrol,
    sign_in_as,
    token_for,
)


async def test_joining_a_class_notes_whether_the_student_has_an_accommodation(db, app) -> None:
    """The fact is looked up when a student joins, and only the fact is kept."""
    from sqlalchemy import update

    from app.models.student import Student

    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    async with factory() as seed:
        await seed.execute(
            update(Student)
            .where(Student.user_id == STUDENT_ID)
            .values(accessibility_need="needs x")
        )
        await seed.commit()
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)
    classroom.accommodations.set(STUDENT_ID, False)

    try:
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
            assert ws.receive_json()["type"] == "ready"
            assert STUDENT_ID in classroom.accommodations
    finally:
        classroom.accommodations.set(STUDENT_ID, False)
        client.post(f"/api/v1/sessions/{session['id']}/end")
