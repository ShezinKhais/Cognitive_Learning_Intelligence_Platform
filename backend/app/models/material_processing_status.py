"""Immutable processing-progress history for each uploaded material."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class MaterialProcessingStatus(Base):
    __tablename__ = "material_processing_status"
    __table_args__ = (
        CheckConstraint(
            (
                "stage IN ('validating', 'extracting', 'chunking', "
                "'embedding', 'generating', 'done', 'failed')"
            ),
            name="ck_material_processing_status_stage",
        ),
        CheckConstraint(
            "percent >= 0 AND percent <= 100",
            name="ck_material_processing_status_percent",
        ),
        CheckConstraint(
            "sequence >= 1",
            name="ck_material_processing_status_sequence_positive",
        ),
        UniqueConstraint(
            "source_material_id",
            "sequence",
            name="uq_material_processing_status_material_sequence",
        ),
    )

    status_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_material.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    percent: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
