"""The Teams app package: the committed manifest and icons stay packageable,
and a package Teams would reject is refused before anyone uploads it.

Owner: General CS, Phase 4.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "package_teams_app.py"
GOOD = {
    "TEAMS_APP_ID": "11111111-1111-1111-1111-111111111111",
    "BOT_ID": "22222222-2222-2222-2222-222222222222",
    "BASE_URL": "https://abc123-5173.euw.devtunnels.ms/",
}


@pytest.fixture(scope="module")
def package() -> ModuleType:
    spec = importlib.util.spec_from_file_location("package_teams_app", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(package: ModuleType) -> str:
    return (package.TEAMS_APP / "manifest.json").read_text("utf-8")


def test_the_committed_manifest_and_icons_are_packageable(package: ModuleType) -> None:
    assert package.file_problems(_manifest(package)) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"TEAMS_APP_ID": "clip"}, "TEAMS_APP_ID must be a GUID"),
        ({"BOT_ID": ""}, "BOT_ID must be a GUID"),
        ({"BASE_URL": "http://localhost:5173"}, "BASE_URL must be an https URL"),
    ],
)
def test_values_teams_would_reject_are_refused(
    package: ModuleType, change: dict, problem: str
) -> None:
    _, problems = package.values({**GOOD, **change})
    assert any(p.startswith(problem) for p in problems)


def test_a_placeholder_nothing_fills_is_refused(package: ModuleType) -> None:
    problems = package.file_problems('{"id": "${{TEAMS_APP_ID}}", "x": "${{NOBODY}}"}')
    assert any("NOBODY" in p for p in problems)


def test_the_package_carries_the_filled_manifest_and_both_icons(
    package: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filled, problems = package.values(GOOD)
    assert problems == []
    for name in ("manifest.json", *package.ICONS):
        (tmp_path / name).write_bytes((package.TEAMS_APP / name).read_bytes())
    monkeypatch.setattr(package, "TEAMS_APP", tmp_path)

    out = package.build(_manifest(package), filled)

    with zipfile.ZipFile(out) as zipped:
        assert sorted(zipped.namelist()) == ["color.png", "manifest.json", "outline.png"]
        manifest = json.loads(zipped.read("manifest.json"))
    assert manifest["id"] == GOOD["TEAMS_APP_ID"]
    assert manifest["bots"][0]["botId"] == GOOD["BOT_ID"]
    assert manifest["validDomains"] == ["abc123-5173.euw.devtunnels.ms"]
    assert (
        manifest["staticTabs"][0]["contentUrl"] == "https://abc123-5173.euw.devtunnels.ms/student"
    )


def test_an_icon_of_the_wrong_size_is_refused(
    package: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teams rejects the upload without saying which icon was wrong."""
    (tmp_path / "color.png").write_bytes((package.TEAMS_APP / "outline.png").read_bytes())
    (tmp_path / "outline.png").write_bytes((package.TEAMS_APP / "outline.png").read_bytes())
    monkeypatch.setattr(package, "TEAMS_APP", tmp_path)

    assert package.file_problems("{}") == ["color.png must be 192x192"]
