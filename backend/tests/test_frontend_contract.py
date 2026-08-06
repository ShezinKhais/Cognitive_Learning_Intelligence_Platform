"""The frontend's API base must match the backend's.

A wrong URL in TypeScript compiles and builds cleanly, then 404s at runtime.
That is exactly what happened when routes moved under /api/v1 and the frontend
kept calling /api/health, so this checks the two agree.
"""

import re
from pathlib import Path

import pytest

from app.main import API_V1

API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api.ts"


def _api_base() -> str:
    source = API_TS.read_text(encoding="utf-8")
    match = re.search(r"export const API_BASE = '([^']+)'", source)
    assert match, "API_BASE not found in frontend/src/api.ts"
    return match.group(1)


@pytest.mark.skipif(not API_TS.exists(), reason="frontend not present")
def test_frontend_base_path_matches_the_backend() -> None:
    assert _api_base() == API_V1, (
        f"frontend calls {_api_base()} but the backend serves {API_V1}"
    )


@pytest.mark.skipif(not API_TS.exists(), reason="frontend not present")
def test_frontend_does_not_hardcode_paths_elsewhere() -> None:
    """Every call should go through apiUrl so there is one place to change."""
    src = API_TS.parent
    offenders = []
    for path in src.rglob("*.ts*"):
        if path.name == "api.ts":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "fetch(" in line and "/api" in line:
                offenders.append(f"{path.name}:{number}")

    assert not offenders, f"hardcoded API paths outside api.ts: {offenders}"
