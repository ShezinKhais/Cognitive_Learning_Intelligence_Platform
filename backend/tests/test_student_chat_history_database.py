"""PostgreSQL integration tests for student-private chat history."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.student_chat_exchange import StudentChatExchange
from app.models.user import User
from app.schemas.identity import Role
from app.services import chat_history_persistence
from tests.session_support import sign_in_as


@pytest.mark.asyncio
async def test_chat_history_is_private_and_deletions_are_scoped(db, app, monkeypatch):
    client, factory, created = db

    # Use the fixture's NullPool factory instead of the application-wide
    # pool, so pytest event loops never share asyncpg connections.
    monkeypatch.setattr(
        chat_history_persistence,
        "get_session_factory",
        lambda: factory,
    )
    alice_id = uuid4()
    bob_id = uuid4()

    async with factory() as session:
        session.add_all(
            [
                User(
                    user_id=alice_id,
                    name="Chat Test Alice",
                    email=f"{alice_id.hex}@chat-history.test",
                    role="student",
                ),
                User(
                    user_id=bob_id,
                    name="Chat Test Bob",
                    email=f"{bob_id.hex}@chat-history.test",
                    role="student",
                ),
            ]
        )
        await session.commit()

    created["user"].extend([alice_id, bob_id])

    alice_request = f"alice-{uuid4().hex}"
    bob_request = f"bob-{uuid4().hex}"

    await chat_history_persistence.save_completed_exchange(
        student_id=alice_id,
        session_id=None,
        request_id=alice_request,
        question="Alice's private question",
        answer="Alice's private answer",
        source="materials",
        citations=[],
        follow_ups=[],
        general=False,
    )

    await chat_history_persistence.save_completed_exchange(
        student_id=bob_id,
        session_id=None,
        request_id=bob_request,
        question="Bob's private question",
        answer="Bob's private answer",
        source="materials",
        citations=[],
        follow_ups=[],
        general=False,
    )

    # Replaying Alice's request must not create a duplicate.
    await chat_history_persistence.save_completed_exchange(
        student_id=alice_id,
        session_id=None,
        request_id=alice_request,
        question="Duplicate question",
        answer="Duplicate answer",
        source="materials",
        citations=[],
        follow_ups=[],
        general=False,
    )

    async with factory() as session:
        alice_count = await session.scalar(
            select(func.count())
            .select_from(StudentChatExchange)
            .where(StudentChatExchange.student_id == alice_id)
        )
        assert alice_count == 1

    sign_in_as(app, alice_id, Role.STUDENT)

    alice_response = client.get("/api/v1/me/chat-history")
    assert alice_response.status_code == 200, alice_response.text
    assert alice_response.headers["cache-control"] == "no-store"

    alice_items = alice_response.json()["items"]
    assert len(alice_items) == 1
    assert alice_items[0]["question"] == "Alice's private question"
    assert alice_items[0]["answer"] == "Alice's private answer"
    assert bob_request not in str(alice_response.json())

    alice_record_id = alice_items[0]["id"]

    sign_in_as(app, bob_id, Role.STUDENT)

    bob_response = client.get("/api/v1/me/chat-history")
    assert bob_response.status_code == 200, bob_response.text

    bob_items = bob_response.json()["items"]
    assert len(bob_items) == 1
    assert bob_items[0]["question"] == "Bob's private question"
    assert alice_request not in str(bob_response.json())

    # Bob must not be able to delete Alice's record.
    other_delete = client.delete(f"/api/v1/me/chat-history/{alice_record_id}")
    assert other_delete.status_code in (204, 404)

    sign_in_as(app, alice_id, Role.STUDENT)

    alice_still_exists = client.get("/api/v1/me/chat-history")
    assert len(alice_still_exists.json()["items"]) == 1

    clear_alice = client.delete("/api/v1/me/chat-history")
    assert clear_alice.status_code == 204

    alice_empty = client.get("/api/v1/me/chat-history")
    assert alice_empty.status_code == 200
    assert alice_empty.json()["items"] == []

    sign_in_as(app, bob_id, Role.STUDENT)

    bob_still_exists = client.get("/api/v1/me/chat-history")
    assert bob_still_exists.status_code == 200
    assert len(bob_still_exists.json()["items"]) == 1

    # Verify the remaining record in PostgreSQL itself.
    async with factory() as session:
        remaining = await session.scalars(
            select(StudentChatExchange.student_id).where(
                StudentChatExchange.student_id.in_([alice_id, bob_id])
            )
        )
        assert list(remaining) == [bob_id]
