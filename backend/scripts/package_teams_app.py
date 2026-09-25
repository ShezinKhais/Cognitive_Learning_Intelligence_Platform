"""Build the Teams app package that is uploaded to Teams.

    python scripts/package_teams_app.py            build teams-app/build/clip.zip
    python scripts/package_teams_app.py --check    check the manifest and icons only

Fills the ${{NAME}} placeholders in teams-app/manifest.json from
teams-app/.env, then from the environment. TEAMS_APP_ID and BOT_ID are the
app and bot registrations' ids, and BASE_URL is where the tabs and the bot
are served, such as a dev tunnel. BASE_DOMAIN is taken from BASE_URL.

Refuses a package Teams would reject: a placeholder left unfilled, an id
that is not a GUID, a base URL that is not HTTPS, or icons of the wrong
size. Uploading it needs the "Upload custom apps" permission.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

TEAMS_APP = Path(__file__).resolve().parents[2] / "teams-app"
PLACEHOLDER = re.compile(r"\$\{\{(\w+)\}\}")
# Teams requires a 192 pixel colour icon and a 32 pixel outline icon.
ICONS = {"color.png": 192, "outline.png": 32}
GUIDS = ("TEAMS_APP_ID", "BOT_ID")


def _dotenv(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and value.strip() and not name.lstrip().startswith("#"):
                found[name.strip()] = value.strip()
    return found


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    return struct.unpack(">II", head[16:24])


def values(env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """The placeholder values, and what is wrong with them."""
    problems = []
    for name in GUIDS:
        try:
            UUID(env.get(name, ""))
        except ValueError:
            problems.append(f"{name} must be a GUID")
    base = urlparse(env.get("BASE_URL", ""))
    if base.scheme != "https" or not base.hostname:
        problems.append("BASE_URL must be an https URL, such as a dev tunnel's")
    filled = {name: env.get(name, "") for name in GUIDS}
    filled["BASE_URL"] = env.get("BASE_URL", "").rstrip("/")
    filled["BASE_DOMAIN"] = base.netloc
    return filled, problems


def file_problems(manifest: str) -> list[str]:
    """What is wrong with the committed manifest and icons."""
    problems = [
        f"the manifest uses ${{{{{name}}}}}, which nothing fills"
        for name in sorted(set(PLACEHOLDER.findall(manifest)) - {*GUIDS, "BASE_URL", "BASE_DOMAIN"})
    ]
    for icon, size in ICONS.items():
        path = TEAMS_APP / icon
        if not path.exists():
            problems.append(f"{icon} is missing")
        elif _png_size(path) != (size, size):
            problems.append(f"{icon} must be {size}x{size}")
    return problems


def build(manifest: str, filled: dict[str, str]) -> Path:
    resolved = PLACEHOLDER.sub(lambda m: filled[m.group(1)], manifest)
    json.loads(resolved)
    out = TEAMS_APP / "build" / "clip.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", resolved)
        for icon in ICONS:
            package.write(TEAMS_APP / icon, icon)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the manifest and icons only")
    args = parser.parse_args(argv)
    manifest = (TEAMS_APP / "manifest.json").read_text("utf-8")
    problems = file_problems(manifest)
    if not args.check:
        env = {**_dotenv(TEAMS_APP / ".env"), **{k: v for k, v in os.environ.items() if v}}
        filled, wrong = values(env)
        problems += wrong
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("manifest and icons are ready" if args.check else f"wrote {build(manifest, filled)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
