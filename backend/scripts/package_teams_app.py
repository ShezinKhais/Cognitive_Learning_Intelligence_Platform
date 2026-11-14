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
    try:
        base = urlparse(env.get("BASE_URL", ""))
    except ValueError:
        return {}, ["BASE_URL must be an https URL on the public app origin"]
    try:
        valid_port = base.port in (None, 443)
    except ValueError:
        valid_port = False
    if (
        base.scheme != "https"
        or not base.hostname
        or not valid_port
        or base.username
        or base.password
        or base.query
        or base.fragment
        or base.path not in ("", "/")
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", base.hostname)
    ):
        problems.append("BASE_URL must be an https URL, such as a dev tunnel's")
    filled = {name: env.get(name, "") for name in GUIDS}
    filled["BASE_URL"] = env.get("BASE_URL", "").rstrip("/")
    filled["BASE_DOMAIN"] = base.hostname or ""
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


CHECK_ENV = {
    "TEAMS_APP_ID": "11111111-1111-1111-1111-111111111111",
    "BOT_ID": "22222222-2222-2222-2222-222222222222",
    "BASE_URL": "https://clip.example.com",
}
REQUIRED_RSC = {
    "OnlineMeeting.ReadBasic.Chat",
    "OnlineMeetingParticipant.Read.Chat",
    "OnlineMeetingNotification.Send.Chat",
}


def resolved_manifest(manifest: str, filled: dict[str, str]) -> dict:
    return json.loads(PLACEHOLDER.sub(lambda match: filled[match.group(1)], manifest))


def deployment_problems(data: dict, filled: dict[str, str]) -> list[str]:
    """Cross-field checks for CLIP's private meeting deployment."""
    problems = []
    if data.get("manifestVersion") != "1.17":
        problems.append("The package must use manifest schema 1.17.")
    base = filled["BASE_URL"]
    bot = filled["BOT_ID"]
    if data.get("id") != filled["TEAMS_APP_ID"] or data.get("validDomains") != [
        filled["BASE_DOMAIN"]
    ]:
        problems.append("App ID and validDomains must match the supplied registration and origin.")
    if data.get("webApplicationInfo") != {
        "id": bot,
        "resource": f"api://{filled['BASE_DOMAIN']}/{bot}",
    }:
        problems.append("SSO must use the configured bot registration and origin.")
    if not any(
        entry.get("botId") == bot and "groupChat" in entry.get("scopes", [])
        for entry in data.get("bots", [])
    ):
        problems.append("The configured bot must be available in group chats.")
    if not any(
        tab.get("configurationUrl") == f"{base}/config"
        and "groupChat" in tab.get("scopes", [])
        and {"meetingChatTab", "meetingDetailsTab", "meetingSidePanel"}
        <= set(tab.get("context", []))
        for tab in data.get("configurableTabs", [])
    ):
        problems.append("The meeting tab must point at /config and support the meeting contexts.")
    if not any(
        tab.get("contentUrl") == f"{base}/open" and "personal" in tab.get("scopes", [])
        for tab in data.get("staticTabs", [])
    ):
        problems.append("The personal tab must point at /open.")
    developer = data.get("developer", {})
    if (
        developer.get("privacyUrl") != f"{base}/privacy"
        or developer.get("termsOfUseUrl") != f"{base}/terms"
    ):
        problems.append("Privacy and terms links must use the deployed origin.")
    permissions = data.get("authorization", {}).get("permissions", {}).get("resourceSpecific", [])
    if not REQUIRED_RSC <= {p.get("name") for p in permissions if p.get("type") == "Application"}:
        problems.append("Required application meeting permissions are missing.")
    return problems


def update_problems(data: dict, previous: dict) -> list[str]:
    def version(manifest: dict) -> tuple[int, ...]:
        value = manifest.get("version", "")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
            raise ValueError("App versions must use major.minor.patch.")
        return tuple(map(int, value.split(".")))

    try:
        newer = version(data) > version(previous)
    except ValueError as exc:
        return [str(exc)]
    if previous.get("id") != data.get("id") or not newer:
        return ["An update must retain the installed app ID and increase the app version."]
    return []


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
    parser.add_argument(
        "--check", action="store_true", help="validate with synthetic IDs and origin"
    )
    parser.add_argument(
        "--schema", type=Path, help="local Microsoft manifest schema (jsonschema required)"
    )
    parser.add_argument("--previous", type=Path, help="installed manifest.json for an update check")
    args = parser.parse_args(argv)
    manifest = (TEAMS_APP / "manifest.json").read_text("utf-8")
    problems = file_problems(manifest)
    env = (
        CHECK_ENV
        if args.check
        else {**_dotenv(TEAMS_APP / ".env"), **{k: v for k, v in os.environ.items() if v}}
    )
    filled, wrong = values(env)
    problems += wrong
    if not problems:
        try:
            data = resolved_manifest(manifest, filled)
            if args.schema:
                import jsonschema

                schema = json.loads(args.schema.read_text("utf-8"))
                validator = jsonschema.Draft4Validator(
                    schema, format_checker=jsonschema.FormatChecker()
                )
                for error in validator.iter_errors(data):
                    location = ".".join(map(str, error.absolute_path)) or "manifest"
                    problems.append(f"Microsoft schema: {location} failed {error.validator}")
            if not problems:
                problems += deployment_problems(data, filled)
                if args.previous:
                    problems += update_problems(data, json.loads(args.previous.read_text("utf-8")))
        except (OSError, ImportError, ValueError, AttributeError, TypeError):
            problems.append("Could not validate the manifest, schema or previous package.")
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("manifest and icons are ready" if args.check else f"wrote {build(manifest, filled)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
