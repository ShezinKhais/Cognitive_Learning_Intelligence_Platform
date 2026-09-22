"""Persistence and queries for live-session events owned by BBIS."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.delivered_question import DeliveredQuestion
from app.models.dynamic_prompt import DynamicPrompt
from app.models.missed_response import MissedResponse
from app.models.session_activity import SessionActivity
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.student_response import StudentResponse


@dataclass(frozen=True)
class SessionDashboardCounts:
    participants: int
    delivered_questions: int
    responses: int
    missed_responses: int
    prompt_outcomes: int
    activities: int


@dataclass(frozen=True)
class SessionDelivery:
    delivery_id: uuid.UUID
    session_id: uuid.UUID
    question_id: uuid.UUID
    delivered_at: datetime
    closes_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    window_seconds: int
    eligible_count: int | None
    respondent_count: int


class LiveEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def student_id_for_user(self, user_id: uuid.UUID) -> uuid.UUID | None:
        result = await self.session.execute(
            select(Student.student_id).where(Student.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def record_participant_join(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        joined_at: datetime | None = None,
    ) -> SessionParticipant | None:
        student_id = await self.student_id_for_user(user_id)

        if student_id is None:
            return None

        seen_at = joined_at or datetime.now(UTC)
        statement = (
            insert(SessionParticipant)
            .values(
                session_id=session_id,
                student_id=student_id,
                joined_at=seen_at,
                last_seen_at=seen_at,
                left_at=None,
                connection_count=1,
            )
            .on_conflict_do_update(
                constraint="uq_session_participant_session_student",
                set_={
                    "last_seen_at": seen_at,
                    "left_at": None,
                    "connection_count": SessionParticipant.connection_count + 1,
                },
            )
            .returning(SessionParticipant)
        )

        participant = (await self.session.execute(statement)).scalar_one()
        await self.session.refresh(participant)
        return participant

    async def record_participant_leave(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        left_at: datetime | None = None,
    ) -> SessionParticipant | None:
        """Mark a participant absent after their final session socket closes.

        connection_count records cumulative joins and reconnects; it is not the
        number of currently open tabs or sockets. Callers must therefore invoke
        this only after the user's last socket for this session disconnects.
        """
        student_id = await self.student_id_for_user(user_id)

        if student_id is None:
            return None

        seen_at = left_at or datetime.now(UTC)
        statement = (
            update(SessionParticipant)
            .where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.student_id == student_id,
            )
            .values(
                last_seen_at=seen_at,
                left_at=seen_at,
            )
            .returning(SessionParticipant)
        )

        return (await self.session.execute(statement)).scalar_one_or_none()

    async def record_question_delivery(
        self,
        *,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        closes_at: datetime,
        window_seconds: int,
        delivered_at: datetime | None = None,
    ) -> DeliveredQuestion:
        sent_at = delivered_at or datetime.now(UTC)
        statement = (
            insert(DeliveredQuestion)
            .values(
                session_id=session_id,
                question_id=question_id,
                delivered_at=sent_at,
                closes_at=closes_at,
                window_seconds=window_seconds,
            )
            .on_conflict_do_nothing(
                constraint="uq_delivered_question_session_question",
            )
            .returning(DeliveredQuestion)
        )

        delivery = (await self.session.execute(statement)).scalar_one_or_none()

        if delivery is not None:
            return delivery

        result = await self.session.execute(
            select(DeliveredQuestion).where(
                DeliveredQuestion.session_id == session_id,
                DeliveredQuestion.question_id == question_id,
            )
        )
        return result.scalar_one()

    async def record_response(
        self,
        *,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        selected_option: int | None,
        free_text: str | None,
        is_correct: bool | None,
        elapsed_ms: int | None,
        submitted_at: datetime | None = None,
    ) -> StudentResponse:
        student_id = await self.student_id_for_user(user_id)

        if student_id is None:
            raise ValidationError(
                "User is not registered as a student.",
                {"user_id": str(user_id)},
            )

        received_at = submitted_at or datetime.now(UTC)
        statement = (
            insert(StudentResponse)
            .values(
                session_id=session_id,
                question_id=question_id,
                student_id=student_id,
                selected_option=selected_option,
                free_text=free_text,
                is_correct=is_correct,
                elapsed_ms=elapsed_ms,
                submitted_at=received_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_student_response_session_student_question",
            )
            .returning(StudentResponse)
        )

        response = (await self.session.execute(statement)).scalar_one_or_none()

        if response is not None:
            return response

        result = await self.session.execute(
            select(StudentResponse).where(
                StudentResponse.session_id == session_id,
                StudentResponse.question_id == question_id,
                StudentResponse.student_id == student_id,
            )
        )
        return result.scalar_one()

    async def record_prompt_outcome(
        self,
        *,
        prompt_id: uuid.UUID,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        escalation: int,
        sent_at: datetime,
        expires_at: datetime,
        result: str,
        responded_at: datetime | None,
    ) -> DynamicPrompt:
        student_id = await self.student_id_for_user(user_id)

        if student_id is None:
            raise ValidationError(
                "User is not registered as a student.",
                {"user_id": str(user_id)},
            )

        statement = (
            insert(DynamicPrompt)
            .values(
                prompt_id=prompt_id,
                session_id=session_id,
                student_id=student_id,
                escalation=escalation,
                sent_at=sent_at,
                expires_at=expires_at,
                response_status=result,
                responded_at=responded_at,
            )
            .on_conflict_do_update(
                index_elements=[DynamicPrompt.prompt_id],
                set_={
                    "response_status": result,
                    "responded_at": responded_at,
                },
            )
            .returning(DynamicPrompt)
        )

        return (await self.session.execute(statement)).scalar_one()

    async def record_activity(
        self,
        *,
        session_id: uuid.UUID,
        event_type: str,
        actor_user_id: uuid.UUID | None = None,
        details: dict[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> SessionActivity:
        activity = SessionActivity(
            session_id=session_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            details=details or {},
            occurred_at=occurred_at or datetime.now(UTC),
        )
        self.session.add(activity)
        await self.session.flush()
        await self.session.refresh(activity)
        return activity

    async def close_question_delivery(
        self,
        *,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        eligible_user_ids: set[uuid.UUID],
        answered_user_ids: set[uuid.UUID],
        reason: str,
        closed_at: datetime | None = None,
    ) -> DeliveredQuestion | None:
        result = await self.session.execute(
            select(DeliveredQuestion)
            .where(
                DeliveredQuestion.session_id == session_id,
                DeliveredQuestion.question_id == question_id,
            )
            .with_for_update()
        )
        delivery = result.scalar_one_or_none()

        if delivery is None:
            return None

        finished_at = closed_at or datetime.now(UTC)
        eligible = eligible_user_ids | answered_user_ids
        missed_user_ids = eligible - answered_user_ids

        delivery.closed_at = finished_at
        delivery.close_reason = reason
        delivery.eligible_count = len(eligible)
        delivery.respondent_count = len(answered_user_ids)

        # A retry may carry a newer answered-user set. Rebuild missed rows so
        # they stay synchronized with the delivery counts.
        await self.session.execute(
            delete(MissedResponse).where(MissedResponse.delivery_id == delivery.delivery_id)
        )

        if missed_user_ids:
            student_rows = await self.session.execute(
                select(Student.user_id, Student.student_id).where(
                    Student.user_id.in_(missed_user_ids)
                )
            )
            missed_values = [
                {
                    "delivery_id": delivery.delivery_id,
                    "student_id": student_id,
                    "reason": reason,
                    "recorded_at": finished_at,
                }
                for _, student_id in student_rows.all()
            ]

            if missed_values:
                await self.session.execute(
                    insert(MissedResponse)
                    .values(missed_values)
                    .on_conflict_do_nothing(
                        constraint="uq_missed_response_delivery_student",
                    )
                )

        await self.session.flush()
        return delivery

    async def list_responses(
        self,
        *,
        session_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[StudentResponse], int]:
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(StudentResponse)
                .where(StudentResponse.session_id == session_id)
            )
        ).scalar_one()

        result = await self.session.execute(
            select(StudentResponse)
            .where(StudentResponse.session_id == session_id)
            .order_by(
                StudentResponse.submitted_at,
                StudentResponse.response_id,
            )
            .limit(limit)
            .offset(offset)
        )

        return list(result.scalars().all()), total

    async def list_participants(
        self,
        *,
        session_id: uuid.UUID,
    ) -> list[SessionParticipant]:
        result = await self.session.execute(
            select(SessionParticipant)
            .where(SessionParticipant.session_id == session_id)
            .order_by(
                SessionParticipant.joined_at,
                SessionParticipant.participant_id,
            )
        )
        return list(result.scalars().all())

    async def list_deliveries(
        self,
        *,
        session_id: uuid.UUID,
    ) -> list[SessionDelivery]:
        response_count = (
            select(func.count(StudentResponse.response_id))
            .where(
                StudentResponse.session_id == DeliveredQuestion.session_id,
                StudentResponse.question_id == DeliveredQuestion.question_id,
            )
            .correlate(DeliveredQuestion)
            .scalar_subquery()
        )

        result = await self.session.execute(
            select(
                DeliveredQuestion,
                response_count.label("persisted_response_count"),
            )
            .where(DeliveredQuestion.session_id == session_id)
            .order_by(
                DeliveredQuestion.delivered_at,
                DeliveredQuestion.delivery_id,
            )
        )

        snapshot_at = datetime.now(UTC)
        deliveries = []

        for delivery, persisted_response_count in result.all():
            abandoned = delivery.closed_at is None and delivery.closes_at <= snapshot_at
            deliveries.append(
                SessionDelivery(
                    delivery_id=delivery.delivery_id,
                    session_id=delivery.session_id,
                    question_id=delivery.question_id,
                    delivered_at=delivery.delivered_at,
                    closes_at=delivery.closes_at,
                    closed_at=(delivery.closes_at if abandoned else delivery.closed_at),
                    close_reason=("process_restart" if abandoned else delivery.close_reason),
                    window_seconds=delivery.window_seconds,
                    eligible_count=(None if abandoned else delivery.eligible_count),
                    respondent_count=(
                        persisted_response_count if abandoned else delivery.respondent_count
                    ),
                )
            )

        return deliveries

    async def list_missed_responses(
        self,
        *,
        session_id: uuid.UUID,
    ) -> list[MissedResponse]:
        result = await self.session.execute(
            select(MissedResponse)
            .join(
                DeliveredQuestion,
                DeliveredQuestion.delivery_id == MissedResponse.delivery_id,
            )
            .where(DeliveredQuestion.session_id == session_id)
            .order_by(
                MissedResponse.recorded_at,
                MissedResponse.missed_response_id,
            )
        )
        return list(result.scalars().all())

    async def list_prompt_outcomes(
        self,
        *,
        session_id: uuid.UUID,
    ) -> list[DynamicPrompt]:
        result = await self.session.execute(
            select(DynamicPrompt)
            .where(DynamicPrompt.session_id == session_id)
            .order_by(
                DynamicPrompt.sent_at,
                DynamicPrompt.prompt_id,
            )
        )
        return list(result.scalars().all())

    async def list_activities(
        self,
        *,
        session_id: uuid.UUID,
    ) -> list[SessionActivity]:
        result = await self.session.execute(
            select(SessionActivity)
            .where(SessionActivity.session_id == session_id)
            .order_by(
                SessionActivity.occurred_at,
                SessionActivity.activity_id,
            )
        )
        return list(result.scalars().all())

    async def dashboard_counts(
        self,
        session_id: uuid.UUID,
    ) -> SessionDashboardCounts:
        participant_count = (
            select(func.count())
            .select_from(SessionParticipant)
            .where(SessionParticipant.session_id == session_id)
            .scalar_subquery()
        )
        delivery_count = (
            select(func.count())
            .select_from(DeliveredQuestion)
            .where(DeliveredQuestion.session_id == session_id)
            .scalar_subquery()
        )
        response_count = (
            select(func.count())
            .select_from(StudentResponse)
            .where(StudentResponse.session_id == session_id)
            .scalar_subquery()
        )
        missed_count = (
            select(func.count())
            .select_from(MissedResponse)
            .join(
                DeliveredQuestion,
                DeliveredQuestion.delivery_id == MissedResponse.delivery_id,
            )
            .where(DeliveredQuestion.session_id == session_id)
            .scalar_subquery()
        )
        prompt_count = (
            select(func.count())
            .select_from(DynamicPrompt)
            .where(DynamicPrompt.session_id == session_id)
            .scalar_subquery()
        )
        activity_count = (
            select(func.count())
            .select_from(SessionActivity)
            .where(SessionActivity.session_id == session_id)
            .scalar_subquery()
        )

        row = (
            await self.session.execute(
                select(
                    participant_count,
                    delivery_count,
                    response_count,
                    missed_count,
                    prompt_count,
                    activity_count,
                )
            )
        ).one()

        return SessionDashboardCounts(
            participants=row[0],
            delivered_questions=row[1],
            responses=row[2],
            missed_responses=row[3],
            prompt_outcomes=row[4],
            activities=row[5],
        )
