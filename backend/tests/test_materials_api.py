"""Tests for BBIS-owned material query endpoints."""

import uuid
from datetime import UTC, datetime

from app.api.v1 import content
from app.auth.store import LECTURER_ID
from app.models.material import Material


class FakeMaterialRepository:
    def __init__(self, materials: list[Material]) -> None:
        self.materials = materials

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        uploaded_by_user_id: uuid.UUID | None = None,
    ) -> tuple[list[Material], int]:
        materials = self.materials

        if uploaded_by_user_id is not None:
            materials = [
                material
                for material in materials
                if material.uploaded_by_user_id == uploaded_by_user_id
            ]

        return materials[offset : offset + limit], len(materials)

    async def get_by_id(
        self,
        material_id: uuid.UUID,
        *,
        uploaded_by_user_id: uuid.UUID | None = None,
    ) -> Material | None:
        return next(
            (
                material
                for material in self.materials
                if material.id == material_id
                and (
                    uploaded_by_user_id is None
                    or material.uploaded_by_user_id == uploaded_by_user_id
                )
            ),
            None,
        )


def _material(
    filename: str,
    uploaded_by_user_id: uuid.UUID = LECTURER_ID,
) -> Material:
    return Material(
        id=uuid.uuid4(),
        uploaded_by_user_id=uploaded_by_user_id,
        filename=filename,
        content_type="application/pdf",
        size_bytes=2048,
        status="completed",
        page_count=4,
        chunk_count=8,
        error=None,
        uploaded_at=datetime.now(UTC),
    )


def test_list_materials_returns_paginated_results(
    as_lecturer,
    monkeypatch,
) -> None:
    materials = [_material("week-1.pdf"), _material("week-2.pdf")]
    repository = FakeMaterialRepository(materials)
    monkeypatch.setattr(
        content,
        "MaterialRepository",
        lambda session: repository,
    )

    response = as_lecturer.get("/api/v1/materials?limit=1&offset=1")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(materials[1].id),
                "filename": "week-2.pdf",
                "content_type": "application/pdf",
                "size_bytes": 2048,
                "status": "completed",
                "page_count": 4,
                "chunk_count": 8,
                "error": None,
                "uploaded_at": materials[1].uploaded_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "total": 2,
        "limit": 1,
        "offset": 1,
    }


def test_get_material_returns_record_or_standard_not_found(
    as_lecturer,
    monkeypatch,
) -> None:
    material = _material("week-3.pdf")
    repository = FakeMaterialRepository([material])
    monkeypatch.setattr(
        content,
        "MaterialRepository",
        lambda session: repository,
    )

    found = as_lecturer.get(f"/api/v1/materials/{material.id}")
    missing_id = uuid.uuid4()
    missing = as_lecturer.get(f"/api/v1/materials/{missing_id}")

    assert found.status_code == 200
    assert found.json()["id"] == str(material.id)
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Material was not found.",
        "detail": {"material_id": str(missing_id)},
    }


def test_students_cannot_read_materials(as_student) -> None:
    list_response = as_student.get("/api/v1/materials")
    detail_response = as_student.get(f"/api/v1/materials/{uuid.uuid4()}")

    assert list_response.status_code == 403
    assert list_response.json()["error"]["code"] == "FORBIDDEN"
    assert detail_response.status_code == 403
    assert detail_response.json()["error"]["code"] == "FORBIDDEN"


def test_lecturer_cannot_read_another_lecturers_material(
    as_lecturer,
    monkeypatch,
) -> None:
    material = _material(
        "private.pdf",
        uploaded_by_user_id=uuid.uuid4(),
    )
    repository = FakeMaterialRepository([material])
    monkeypatch.setattr(
        content,
        "MaterialRepository",
        lambda session: repository,
    )

    listed = as_lecturer.get("/api/v1/materials")
    found = as_lecturer.get(f"/api/v1/materials/{material.id}")

    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert listed.json()["total"] == 0
    assert found.status_code == 404
    assert found.json()["error"]["code"] == "NOT_FOUND"
