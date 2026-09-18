from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import ValidationError
from app.services.extraction import (
    ContentChunk,
    ExtractedElement,
    ProcessingResult,
)
from app.services.processing_security import validate_processing_result


def make_result(
    *,
    page_count: int = 1,
    extracted_characters: int = 100,
    chunk_count: int = 1,
) -> ProcessingResult:
    material_id = uuid4()

    elements = [
        ExtractedElement(
            el_type="text",
            content="A" * extracted_characters,
            page=1,
        )
    ]

    chunks = [
        ContentChunk(
            chunk_id=uuid4(),
            chunk_index=index,
            material_id=material_id,
            chunk_text=f"Chunk {index}",
            source_page=1,
        )
        for index in range(chunk_count)
    ]

    return ProcessingResult(
        material_id=material_id,
        elements=elements,
        chunks=chunks,
        page_count=page_count,
        parser_used="test-parser",
        warnings=[],
    )


def test_material_with_too_many_pages_is_rejected() -> None:
    result = make_result(
        page_count=11,
    )

    settings = Settings(
        _env_file=None,
        max_material_pages=10,
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_processing_result(
            result,
            settings,
        )

    assert exc_info.value.message == "Material contains too many pages or slides"


def test_material_with_too_much_extracted_text_is_rejected() -> None:
    result = make_result(
        extracted_characters=1001,
    )

    settings = Settings(
        _env_file=None,
        max_extracted_characters=1000,
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_processing_result(
            result,
            settings,
        )

    assert exc_info.value.message == "Material contains too much extracted text"


def test_material_with_too_many_chunks_is_rejected() -> None:
    result = make_result(
        chunk_count=6,
    )

    settings = Settings(
        _env_file=None,
        max_material_chunks=5,
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_processing_result(
            result,
            settings,
        )

    assert exc_info.value.message == "Material produced too many processing chunks"


def test_normal_processing_result_is_accepted() -> None:
    result = make_result(
        page_count=25,
        extracted_characters=5000,
        chunk_count=20,
    )

    settings = Settings(
        _env_file=None,
        max_material_pages=100,
        max_extracted_characters=10_000,
        max_material_chunks=100,
    )

    validate_processing_result(
        result,
        settings,
    )
