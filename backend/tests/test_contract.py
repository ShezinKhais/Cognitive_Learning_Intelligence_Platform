"""Guards on the frozen API contract.

These fail loudly when someone changes the shared interface, which is the point:
five other workstreams build against it.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent

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


def _export_contract() -> ModuleType:
    """Load scripts/export_contract.py by path.

    It is a script rather than part of the installed package, so there is no
    module name to import it under.
    """
    path = BACKEND / "scripts" / "export_contract.py"
    spec = importlib.util.spec_from_file_location("export_contract", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openapi_generates(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"]


def test_contract_paths_are_unchanged(client: TestClient) -> None:
    """Both directions matter.

    Removing or renaming a path breaks the five workstreams building against
    it. Adding one silently widens a surface six people agreed to freeze, and
    an unreviewed route is how a half-finished handler reaches a branch nobody
    thought to look at. Either change belongs in this list, in the same commit
    that makes it, where a reviewer will see it.
    """
    actual = set(client.get("/api/v1/openapi.json").json()["paths"])
    assert actual == EXPECTED_PATHS, (
        f"removed or renamed: {sorted(EXPECTED_PATHS - actual)}, "
        f"added without updating EXPECTED_PATHS: {sorted(actual - EXPECTED_PATHS)}"
    )


def test_the_committed_contract_matches_the_code() -> None:
    """The generated document is not the one anyone else reads.

    Every other workstream builds against the committed openapi.json and
    events.schema.json, and those files only change when somebody remembers to
    run the export script. Every other test here asks the running app, so a
    stale file is invisible to all of them. CI checks it in a separate step,
    which is exactly why drift on another branch went unnoticed until someone
    looked by hand. Running the same check here means pytest catches it.
    """
    export = _export_contract()
    stale = [
        path.name
        for path, render in export.TARGETS
        if not path.exists() or export._read(path) != render()
    ]
    assert not stale, (
        f"the committed contract is out of date: {', '.join(stale)}. "
        f"Run: python scripts/export_contract.py"
    )


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


def test_engagement_reports_confidence_and_available_signals(
    client: TestClient,
) -> None:
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
