"""Persistence and processing-status queries for uploaded materials."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.models.material_processing_status import MaterialProcessingStatus
from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage


class MaterialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(
        self,
        material_id: uuid.UUID,
        *,
        uploaded_by_user_id: uuid.UUID | None = None,
    ) -> Material | None:
        query = select(Material).where(Material.id == material_id)

        if uploaded_by_user_id is not None:
            query = query.where(Material.uploaded_by_user_id == uploaded_by_user_id)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        uploaded_by_user_id: uuid.UUID | None = None,
    ) -> tuple[list[Material], int]:
        query = select(Material)
        count_query = select(func.count()).select_from(Material)

        if uploaded_by_user_id is not None:
            owner_filter = Material.uploaded_by_user_id == uploaded_by_user_id
            query = query.where(owner_filter)
            count_query = count_query.where(owner_filter)

        total = (await self.session.execute(count_query)).scalar_one()

        result = await self.session.execute(
            query.order_by(Material.uploaded_at.desc(), Material.id).limit(limit).offset(offset)
        )

        return list(result.scalars().all()), total

    async def create(
        self,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        uploaded_by_user_id: uuid.UUID,
        course_id: uuid.UUID | None = None,
    ) -> Material:
        material = Material(
            course_id=course_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            status=MaterialStatus.PENDING.value,
        )
        self.session.add(material)
        await self.session.flush()
        await self.session.refresh(material)
        return material

    async def record_progress(
        self,
        *,
        material_id: uuid.UUID,
        stage: MaterialStage,
        percent: int,
        message: str | None = None,
    ) -> MaterialProcessingStatus | None:
        material = (
            await self.session.execute(
                select(Material).where(Material.id == material_id).with_for_update()
            )
        ).scalar_one_or_none()

        if material is None:
            return None
        next_sequence = (
            await self.session.execute(
                select(
                    func.coalesce(
                        func.max(MaterialProcessingStatus.sequence),
                        0,
                    )
                    + 1
                ).where(MaterialProcessingStatus.source_material_id == material_id)
            )
        ).scalar_one()
        progress = MaterialProcessingStatus(
            source_material_id=material_id,
            sequence=next_sequence,
            stage=stage.value,
            percent=percent,
            message=message,
        )
        material.status = stage.material_status.value

        if stage is MaterialStage.FAILED:
            material.error = message
        elif stage is MaterialStage.DONE:
            material.error = None

        self.session.add(progress)
        await self.session.flush()
        await self.session.refresh(progress)
        return progress

    async def list_status_history(
        self,
        material_id: uuid.UUID,
    ) -> list[MaterialProcessingStatus]:
        result = await self.session.execute(
            select(MaterialProcessingStatus)
            .where(MaterialProcessingStatus.source_material_id == material_id)
            .order_by(MaterialProcessingStatus.sequence)
        )
        return list(result.scalars().all())
