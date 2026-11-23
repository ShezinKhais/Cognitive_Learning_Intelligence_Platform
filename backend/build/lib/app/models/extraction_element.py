"""Extraction elements preserve the structure and source location of material content."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class ExtractionElement(Base):
    __tablename__ = "extraction_element"
    __table_args__ = (
        CheckConstraint(
            "element_index >= 0",
            name="ck_extraction_element_index_nonnegative",
        ),
        CheckConstraint(
            "source_page IS NULL OR source_page >= 1",
            name="ck_extraction_element_source_page_positive",
        ),
        UniqueConstraint(
            "source_material_id",
            "element_index",
            name="uq_extraction_element_material_index",
        ),
    )

    element_id: Mapped[uuid.UUID] = mapped_column(
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
    element_index: Mapped[int] = mapped_column(Integer, nullable=False)
    element_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
