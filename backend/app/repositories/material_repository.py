"""Persistence and processing-status queries for uploaded materials."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.models.material_processing_status import MaterialProcessingStatus
from app.schemas.content import MaterialStatus
from app.schemas.events import MaterialStage

_STAGE_TO_MATERIAL_STATUS = {
    MaterialStage.VALIDATING: MaterialStatus.PROCESSING,
    MaterialStage.EXTRACTING: MaterialStatus.PROCESSING,
    MaterialStage.CHUNKING: MaterialStatus.PROCESSING,
    MaterialStage.EMBEDDING: MaterialStatus.PROCESSING,
    MaterialStage.GENERATING: MaterialStatus.PROCESSING,
    MaterialStage.DONE: MaterialStatus.COMPLETED,
    MaterialStage.FAILED: MaterialStatus.FAILED,
}


class MaterialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, material_id: uuid.UUID) -> Material | None:
        return await self.session.get(Material, material_id)

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Material], int]:
        total = (
            await self.session.execute(select(func.count()).select_from(Material))
        ).scalar_one()

        result = await self.session.execute(
            select(Material)
            .order_by(Material.uploaded_at.desc(), Material.id)
            .limit(limit)
            .offset(offset)
        )

        return list(result.scalars().all()), total

    async def create(
        self,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        course_id: uuid.UUID | None = None,
    ) -> Material:
        material = Material(
            course_id=course_id,
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
        material = await self.get_by_id(material_id)

        if material is None:
            return None

        progress = MaterialProcessingStatus(
            source_material_id=material_id,
            stage=stage.value,
            percent=percent,
            message=message,
        )
        material.status = _STAGE_TO_MATERIAL_STATUS[stage].value

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
            .order_by(
                MaterialProcessingStatus.recorded_at,
                MaterialProcessingStatus.status_id,
            )
        )
        return list(result.scalars().all())
