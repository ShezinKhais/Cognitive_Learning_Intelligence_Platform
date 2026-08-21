"""Database queries for students."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import Student


class StudentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, student_id: uuid.UUID) -> Student | None:
        return await self.session.get(Student, student_id)

    async def get_by_user_id(self, user_id: uuid.UUID) -> Student | None:
        result = await self.session.execute(select(Student).where(Student.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_by_course(self, course_id: uuid.UUID) -> list[Student]:
        result = await self.session.execute(
            select(Student)
            .where(Student.course_id == course_id)
            .order_by(Student.enrolled_at, Student.student_id)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        consent_status: str,
        enrolled_at: date,
        accessibility_need: str | None = None,
        attention_threshold: str | None = None,
        special_consideration_status: str | None = None,
    ) -> Student:
        student = Student(
            user_id=user_id,
            course_id=course_id,
            accessibility_need=accessibility_need,
            consent_status=consent_status,
            attention_threshold=attention_threshold,
            special_consideration_status=special_consideration_status,
            enrolled_at=enrolled_at,
        )
        self.session.add(student)
        await self.session.flush()
        await self.session.refresh(student)
        return student
