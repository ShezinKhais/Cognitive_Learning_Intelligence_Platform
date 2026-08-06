"""Database queries for users."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def list_by_role(self, role: str) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(User.role == role)
            .order_by(User.name)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        name: str,
        role: str,
        email: str,
    ) -> User:
        user = User(name=name, role=role, email=email)
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user