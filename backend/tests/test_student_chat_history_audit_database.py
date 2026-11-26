"""Verify durable audit records for private chatbot-history deletion."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import delete, select

from app.api.deps import Principal
from app.api.v1.student_chat_history import (
    delete_my_chat_exchange,
    delete_my_chat_history,
)
from app.models.audit_log import AuditLog
from app.models.student_chat_exchange import StudentChatExchange
from app.models.user import User
from app.schemas.identity import Role


@pytest.mark.asyncio
async def test_history_deletions_write_private_production_audit_records(db):
    _client, factory, created = db

    student_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()

    async with factory() as session:
        session.add(
            User(
                user_id=student_id,
                name="Chat Audit Test Student",
                email=f"{student_id.hex}@chat-history.test",
                role="student",
            )
        )
        await session.commit()

    created["user"].append(student_id)

    async with factory() as session:
        for exchange_id, question in (
            (first_id, "Private question one"),
            (second_id, "Private question two"),
        ):
            session.add(
                StudentChatExchange(
                    id=exchange_id,
                    student_id=student_id,
                    session_id=None,
                    request_id=uuid4().hex,
                    question=question,
                    answer=f"Confidential answer for {question}",
                    source="materials",
                    phase="completed",
                    citations=[],
                    follow_ups=[],
                    general=False,
                    explanation=None,
                )
            )
        await session.commit()

    principal = Principal(
        user_id=student_id,
        role=Role.STUDENT,
        email="audit-test@chat-history.test",
    )
    settings = SimpleNamespace(is_production=True)

    # Call the decorated handlers directly with production auditing enabled.
    # Their changes and audit entries are committed in the same transaction.
    async with factory() as session:
        await delete_my_chat_exchange(
            exchange_id=first_id,
            principal=principal,
            db=session,
            response=Response(),
            settings=settings,
        )
        await session.commit()

    async with factory() as session:
        await delete_my_chat_history(
            principal=principal,
            db=session,
            response=Response(),
            settings=settings,
        )
        await session.commit()

    actions = {
        "STUDENT_CHAT_EXCHANGE_DELETED",
        "STUDENT_CHAT_HISTORY_CLEARED",
    }

    async with factory() as session:
        rows = list(
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.user_id == student_id,
                    AuditLog.action_type.in_(actions),
                )
            )
        )

        assert len(rows) == 2
        assert {row.action_type for row in rows} == actions

        for row in rows:
            assert row.user_id == student_id
            assert "Private question" not in str(row.details)
            assert "Confidential answer" not in str(row.details)

        remaining = list(
            await session.scalars(
                select(StudentChatExchange.id).where(StudentChatExchange.student_id == student_id)
            )
        )
        assert remaining == []

        # Audit records are intentionally retained by the application.
        # Remove only this test's audit rows before fixture cleanup.
        await session.execute(
            delete(AuditLog).where(
                AuditLog.user_id == student_id,
                AuditLog.action_type.in_(actions),
            )
        )
        await session.commit()
