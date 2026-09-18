"""Security limits applied after lecture-material extraction.

Owner: Cyber 1, Phase 2.

A file can be small and structurally valid while still producing an excessive
number of pages, extracted characters or chunks. These checks run before
embedding and question generation so one document cannot consume unreasonable
processing resources.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import ValidationError
from app.services.extraction import ProcessingResult


def validate_processing_result(
    result: ProcessingResult,
    settings: Settings,
) -> None:
    """Reject extracted material that exceeds safe processing limits."""

    if result.page_count > settings.max_material_pages:
        raise ValidationError(
            "Material contains too many pages or slides",
            {
                "page_count": result.page_count,
                "max_pages": settings.max_material_pages,
            },
        )

    extracted_characters = sum(
        len(element.content) for element in result.elements if element.el_type != "image"
    )

    if extracted_characters > settings.max_extracted_characters:
        raise ValidationError(
            "Material contains too much extracted text",
            {
                "extracted_characters": extracted_characters,
                "max_characters": settings.max_extracted_characters,
            },
        )

    if len(result.chunks) > settings.max_material_chunks:
        raise ValidationError(
            "Material produced too many processing chunks",
            {
                "chunk_count": len(result.chunks),
                "max_chunks": settings.max_material_chunks,
            },
        )
