"""Database queries for courses."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course


class CourseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, course_id: uuid.UUID) -> Course | None:
        return await self.session.get(Course, course_id)

    async def get_by_code(self, code: str) -> Course | None:
        result = await self.session.execute(
            select(Course).where(Course.code == code)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Course]:
        result = await self.session.execute(
            select(Course).order_by(Course.code)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        code: str,
        name: str,
        department: str | None = None,
    ) -> Course:
        course = Course(
            code=code,
            name=name,
            department=department,
        )
        self.session.add(course)
        await self.session.flush()
        await self.session.refresh(course)
        return course