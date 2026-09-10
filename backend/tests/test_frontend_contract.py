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
    assert _api_base() == API_V1, f"frontend calls {_api_base()} but the backend serves {API_V1}"


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


ENTRY_POINT = API_TS.parent / "main.tsx"

# Bare specifiers ('react', 'lucide-react') are dependencies, not our source.
RELATIVE_IMPORT = re.compile(r"""(?:from|import)\s+['"](\.{1,2}/[^'"]+|@/[^'"]+)['"]""")

# Vite resolves an extensionless import by trying these in order.
CANDIDATE_SUFFIXES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")


def _resolve(specifier: str, importer: Path, src: Path) -> Path | None:
    """Turn one import specifier into the file it loads, the way Vite does."""
    if specifier.startswith("@/"):
        base = src / specifier[2:]
    else:
        base = (importer.parent / specifier).resolve()

    for suffix in CANDIDATE_SUFFIXES:
        candidate = Path(str(base) + suffix)
        if candidate.is_file():
            return candidate
    return None


def _reachable_from_entry_point(src: Path) -> set[Path]:
    """Walk imports out from main.tsx and collect every module they reach."""
    seen: set[Path] = set()
    queue = [ENTRY_POINT]

    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)

        for specifier in RELATIVE_IMPORT.findall(current.read_text(encoding="utf-8")):
            target = _resolve(specifier, current, src)
            if target is not None and target.suffix in {".ts", ".tsx"}:
                queue.append(target)

    return seen


@pytest.mark.skipif(not ENTRY_POINT.exists(), reason="frontend not present")
def test_every_frontend_module_is_reachable_from_the_entry_point() -> None:
    """No page may sit in the tree while nothing routes to it.

    Vite drops a module nothing imports, so an unrouted page costs no bundle
    size and raises no error: tsc, the linter and the build all pass while the
    feature is simply absent. That is how the admin console and the consent
    page were built, reviewed, merged, and then shipped to nobody. A missing
    import is invisible; a failing test is not.
    """
    src = API_TS.parent
    reachable = _reachable_from_entry_point(src)

    orphans = sorted(
        str(path.relative_to(src)).replace("\\", "/")
        for path in src.rglob("*.ts*")
        if path.is_file() and path not in reachable
    )

    assert not orphans, (
        "these modules are in the tree but nothing imports them, so Vite "
        f"leaves them out of the bundle entirely: {orphans}"
    )
