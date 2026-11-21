"""The release record prints only safe values, and every prompt version it names exists."""

import importlib.util
from pathlib import Path

from app.core.config import Settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_release.py"


def _record():
    spec = importlib.util.spec_from_file_location("record_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_prompt_version_it_names_exists() -> None:
    versions = _record().prompt_versions()
    assert versions and "missing" not in versions.values()


def test_only_true_false_switches_are_printed() -> None:
    settings = Settings(client_secret="not-for-evidence", clip_secret_key="x" * 40)
    switches = _record().switches(settings)
    assert switches and all(isinstance(value, bool) for value in switches.values())
    assert "client_secret" not in switches and "database_url" not in switches


def test_the_package_list_is_summarised_not_listed() -> None:
    packages = _record().packages()
    assert set(packages) == {"count", "sha256"} and len(packages["sha256"]) == 64
