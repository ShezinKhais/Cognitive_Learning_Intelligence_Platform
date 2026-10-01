"""What a live session stores, against a real database: the delivery a
close completes, and who attended.

Owner: General CS, Phase 3, for the wiring; BBIS owns the tables.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select

from app.auth.store import (
    LECTURER_ID,
)
from app.models.delivered_question import DeliveredQuestion
from app.models.question import Question
from app.models.session_participant import SessionParticipant
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


async def test_a_close_completes_the_delivery_its_claim_recorded(db, app) -> None:
    """Closes were stored nowhere: the close recorder completes the delivery
    row, and nothing wrote one. The claim writes it, in the transaction that
    marks the question delivered, so the two cannot disagree."""
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    question_id = await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        assert ws.receive_json()["type"] == "ready"
        ws.receive_json()
        client.post(f"/api/v1/sessions/{session['id']}/questions/{question_id}:deliver")
        assert ws.receive_json()["type"] == "question.delivered"
        ws.send_json(
            {
                "type": "answer.submit",
                "data": {
                    "question_id": str(question_id),
                    "selected_option": 1,
                    "client_elapsed_ms": 900,
                },
            }
        )
        assert ws.receive_json()["data"]["accepted"] is True
        client.post(f"/api/v1/sessions/{session['id']}/end")

    async with factory() as check:
        delivery = (
            await check.execute(
                select(DeliveredQuestion).where(DeliveredQuestion.session_id == UUID(session["id"]))
            )
        ).scalar_one()
        status = await check.scalar(
            select(Question.status).where(Question.question_id == question_id)
        )

    assert (delivery.question_id, status) == (question_id, "delivered")
    assert delivery.closed_at is not None
    assert delivery.close_reason == "session_ended"
    assert (delivery.eligible_count, delivery.respondent_count) == (1, 1)


async def test_a_student_who_joins_and_leaves_is_recorded_as_attending(db, app) -> None:
    """record_participant_join and record_participant_leave had no caller.
    The socket reports both through the classroom, which knows whether it was
    the student's last tab."""
    client, factory, created = db
    course = await add_course(factory, created)
    await enrol(factory, course)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    client.post(f"/api/v1/sessions/{session['id']}/start")
    token = token_for(client, "student@clip.example.com", STUDENT_PASSWORD)

    async def attendance() -> SessionParticipant:
        async with factory() as check:
            return (
                await check.execute(
                    select(SessionParticipant).where(
                        SessionParticipant.session_id == UUID(session["id"])
                    )
                )
            ).scalar_one()

    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "auth", "data": {"token": token, "session_id": session["id"]}})
        assert ws.receive_json()["type"] == "ready"
        ws.receive_json()
        # The pong comes from the receive loop, which starts after the arrival.
        ws.send_json({"type": "ping", "data": {}})
        ws.receive_json()
        present = await attendance()
        assert (present.connection_count, present.left_at) == (1, None)

        # Closed from the client while the test client still runs the handler:
        # leaving the block would cancel it, which a real server does not do.
        ws.close()
        for _ in range(50):
            if (await attendance()).left_at is not None:
                break
            await asyncio.sleep(0.05)

    assert (await attendance()).left_at is not None
