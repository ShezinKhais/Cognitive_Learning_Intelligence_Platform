"""Guards on the frozen API contract.

These fail loudly when someone changes the shared interface, which is the point:
five other workstreams build against it.
"""

from fastapi.testclient import TestClient

EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/auth/consent",
    "/api/v1/admin/timetable",
    "/api/v1/admin/roster",
    "/api/v1/materials",
    "/api/v1/materials/{material_id}",
    "/api/v1/materials/{material_id}/questions",
    "/api/v1/materials/{material_id}/questions/{question_id}",
    "/api/v1/materials/{material_id}/questions:bulk",
    "/api/v1/sessions",
    "/api/v1/sessions/{session_id}",
    "/api/v1/sessions/{session_id}/start",
    "/api/v1/sessions/{session_id}/end",
    "/api/v1/sessions/{session_id}/questions/{question_id}:deliver",
    "/api/v1/sessions/{session_id}/responses",
    "/api/v1/sessions/{session_id}/engagement",
    "/api/v1/sessions/{session_id}/alerts",
    "/api/v1/sessions/{session_id}/summary/{student_id}",
}


def test_openapi_generates(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"]


def test_contract_paths_are_unchanged(client: TestClient) -> None:
    """Adding a path is fine. Removing or renaming one breaks other people."""
    actual = set(client.get("/api/v1/openapi.json").json()["paths"])
    missing = EXPECTED_PATHS - actual
    assert not missing, f"contract paths removed or renamed: {sorted(missing)}"


def test_everything_is_versioned(client: TestClient) -> None:
    for path in client.get("/api/v1/openapi.json").json()["paths"]:
        assert path.startswith("/api/v1/"), f"{path} is outside the versioned prefix"


def test_engagement_and_comprehension_stay_separate(client: TestClient) -> None:
    """The design rests on these being distinct measures. A single schema
    carrying both would be the first step to merging them."""
    schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
    engagement = schemas["EngagementOut"]["properties"]
    assert "score" in engagement
    assert not any("comprehension" in name.lower() for name in engagement)


def test_engagement_reports_confidence_and_available_signals(client: TestClient) -> None:
    """A low-signal student must be reportable as 'insufficient data' rather
    than 'disengaged', which needs both of these fields."""
    engagement = client.get("/api/v1/openapi.json").json()["components"]["schemas"]["EngagementOut"]
    assert "confidence" in engagement["properties"]
    assert "signals_available" in engagement["properties"]

    schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
    assert "insufficient_data" in schemas["EngagementStatus"]["enum"]


def test_no_event_type_can_carry_raw_media(client: TestClient) -> None:
    """The privacy commitment is architectural: there is deliberately no event
    shape capable of transporting frames, audio or transcripts."""
    schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
    banned = ("image", "frame", "audio", "transcript", "recording", "blob")

    for name, schema in schemas.items():
        for field in schema.get("properties", {}):
            assert not any(word in field.lower() for word in banned), (
                f"{name}.{field} looks like raw media"
            )


def test_bearer_security_is_documented(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    scheme = spec["components"]["securitySchemes"]["BearerAuth"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    assert "security" not in spec["paths"]["/api/v1/auth/login"]["post"]
    assert spec["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"BearerAuth": []}]
    assert spec["paths"]["/api/v1/admin/timetable"]["post"]["security"] == [{"BearerAuth": []}]
