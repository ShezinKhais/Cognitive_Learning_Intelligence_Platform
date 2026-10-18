"""The frontend's API base must match the backend's.

A wrong URL in TypeScript compiles and builds cleanly, then 404s at runtime.
That is exactly what happened when routes moved under /api/v1 and the frontend
kept calling /api/health, so this checks the two agree.
"""

import json
import re
from pathlib import Path

import pytest

from app.main import API_V1

API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api.ts"
APP_TSX = API_TS.parent / "App.tsx"
TEAMS_MANIFEST = API_TS.parents[2] / "teams-app" / "manifest.json"


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


@pytest.mark.skipif(
    not APP_TSX.exists() or not TEAMS_MANIFEST.exists(),
    reason="frontend or Teams manifest not present",
)
def test_teams_lecturer_tab_has_a_matching_frontend_route() -> None:
    """The Teams lecturer tab must not fall through to the student page."""
    manifest = json.loads(TEAMS_MANIFEST.read_text(encoding="utf-8"))
    lecturer_tab = next(tab for tab in manifest["staticTabs"] if tab["entityId"] == "clip.lecturer")
    route = lecturer_tab["contentUrl"].replace("${{BASE_URL}}", "")

    assert f'path="{route}"' in APP_TSX.read_text(encoding="utf-8")


ENTRY_POINT = API_TS.parent / "main.tsx"

# Bare specifiers ('react', 'lucide-react') are dependencies, not our source.
RELATIVE_IMPORT = re.compile(r"""(?:from\s+|import\s*(?:\(\s*)?)['"](\.{1,2}/[^'"]+|@/[^'"]+)['"]""")
# Vite bundles worker entry points separately; they are not ordinary imports.
WORKER_IMPORT = re.compile(
    r"""new\s+(?:SharedWorker|Worker)\s*\(\s*new\s+URL\s*\(\s*['"]"""
    r"""(\.{1,2}/[^'"]+)['"]\s*,\s*import\.meta\.url\s*\)"""
)

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
    queue = [src / "main.tsx"]

    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)

        source = current.read_text(encoding="utf-8")
        for specifier in RELATIVE_IMPORT.findall(source) + WORKER_IMPORT.findall(source):
            target = _resolve(specifier, current, src)
            if target is not None and target.suffix in {".ts", ".tsx"}:
                queue.append(target)

    return seen


@pytest.mark.parametrize("constructor", ["Worker", "SharedWorker"])
def test_reachability_follows_worker_and_its_imports(tmp_path: Path, constructor: str) -> None:
    (tmp_path / "main.tsx").write_text(
        f"new {constructor}(\n new URL('./face.worker.ts', import.meta.url), {{ type: 'module' }})",
        encoding="utf-8",
    )
    (tmp_path / "face.worker.ts").write_text("import './signals'", encoding="utf-8")
    (tmp_path / "signals.ts").write_text("export const value = 1", encoding="utf-8")
    # An unrelated worker is still an orphan: do not exempt all *.worker.ts files.
    (tmp_path / "unused.worker.ts").write_text("export {}", encoding="utf-8")
    assert {path.name for path in _reachable_from_entry_point(tmp_path)} == {
        "main.tsx",
        "face.worker.ts",
        "signals.ts",
    }


def test_reachability_follows_lazy_dynamic_imports(tmp_path: Path) -> None:
    """Lazy-loaded pages and their dependencies are reachable from the entry point."""
    (tmp_path / "main.tsx").write_text(
        "const page = lazy(() => import('./LazyPage'))",
        encoding="utf-8",
    )
    (tmp_path / "LazyPage.tsx").write_text(
        "import { value } from './dependency'\nexport default value",
        encoding="utf-8",
    )
    (tmp_path / "dependency.ts").write_text(
        "export const value = 1",
        encoding="utf-8",
    )
    (tmp_path / "orphan.ts").write_text(
        "export const unused = true",
        encoding="utf-8",
    )

    assert {path.name for path in _reachable_from_entry_point(tmp_path)} == {
        "main.tsx",
        "LazyPage.tsx",
        "dependency.ts",
    }

def test_asset_url_does_not_make_a_worker_reachable(tmp_path: Path) -> None:
    (tmp_path / "main.tsx").write_text(
        "const asset = new URL('./unused.worker.ts', import.meta.url)", encoding="utf-8"
    )
    (tmp_path / "unused.worker.ts").write_text("export {}", encoding="utf-8")
    assert _reachable_from_entry_point(tmp_path) == {tmp_path / "main.tsx"}


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
