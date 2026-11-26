"""Privacy and ownership checks for student chatbot history."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Response

from app.api.deps import Principal
from app.api.v1.student_chat_history import (
    delete_my_chat_exchange,
    delete_my_chat_history,
    my_chat_history,
)
from app.schemas.identity import Role


def _principal(user_id):
    return Principal(
        user_id=user_id,
        role=Role.STUDENT,
        email="student@example.com",
    )


def _bound_values(statement):
    return list(statement.compile().params.values())


def test_lecturer_cannot_access_chat_history(as_lecturer):
    base = "/api/v1/me/chat-history"
    exchange_id = uuid4()

    assert as_lecturer.get(base).status_code == 403
    assert as_lecturer.delete(base).status_code == 403
    assert as_lecturer.delete(f"{base}/{exchange_id}").status_code == 403


def test_admin_cannot_access_chat_history(as_admin):
    base = "/api/v1/me/chat-history"
    exchange_id = uuid4()

    assert as_admin.get(base).status_code == 403
    assert as_admin.delete(base).status_code == 403
    assert as_admin.delete(f"{base}/{exchange_id}").status_code == 403


@pytest.mark.asyncio
async def test_history_query_uses_authenticated_student_id():
    student_id = uuid4()
    another_student_id = uuid4()

    row = SimpleNamespace(
        id=uuid4(),
        student_id=student_id,
        session_id=None,
        request_id="request-1",
        question="Explain recursion",
        answer="What happens at the base case?",
        source="materials",
        phase="completed",
        citations=[],
        follow_ups=[],
        general=False,
        explanation=None,
        created_at=datetime.now(UTC),
    )

    db = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
    )

    response = Response()
    result = await my_chat_history(_principal(student_id), db, response, limit=25, offset=0)

    assert response.headers["cache-control"] == "no-store"
    assert result["total"] == 1
    assert result["items"][0]["question"] == "Explain recursion"

    for statement in (
        db.scalar.await_args.args[0],
        db.scalars.await_args.args[0],
    ):
        values = _bound_values(statement)
        assert student_id in values
        assert another_student_id not in values


@pytest.mark.asyncio
async def test_delete_all_is_scoped_to_authenticated_student():
    settings = SimpleNamespace(is_production=False)
    student_id = uuid4()
    db = SimpleNamespace(execute=AsyncMock())

    response = Response()
    await delete_my_chat_history(_principal(student_id), db, response, settings)

    statement = db.execute.await_args.args[0]
    assert student_id in _bound_values(statement)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_delete_one_requires_both_owner_and_exchange_id():
    settings = SimpleNamespace(is_production=False)
    student_id = uuid4()
    exchange_id = uuid4()
    db = SimpleNamespace(execute=AsyncMock())

    response = Response()
    await delete_my_chat_exchange(exchange_id, _principal(student_id), db, response, settings)

    values = _bound_values(db.execute.await_args.args[0])
    assert student_id in values
    assert exchange_id in values
    assert response.headers["cache-control"] == "no-store"
