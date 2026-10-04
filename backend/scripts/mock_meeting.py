"""Play a Teams meeting against a running backend, without Teams.

    python scripts/mock_meeting.py link  <meeting_id> <session_id>
    python scripts/mock_meeting.py start <meeting_id> [--course CODE] [--title TITLE]
    python scripts/mock_meeting.py end   <meeting_id>

This is the mock adapter: it posts what the Teams bot would, to the meeting
routes, as the development lecturer. The token is signed here with the local
CLIP_SECRET_KEY, so it only works against a backend sharing this .env, and
refuses to run in production. --base points it elsewhere, such as a dev
tunnel.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from app.auth.store import LECTURER_ID
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.identity import Role

LECTURER_EMAIL = "lecturer@clip.example.com"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["link", "start", "end"])
    parser.add_argument("meeting_id")
    parser.add_argument("session_id", nargs="?")
    parser.add_argument("--course", help="creates a session for an unlinked meeting on start")
    parser.add_argument("--title")
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.is_production:
        print("refusing to sign a development token in production", file=sys.stderr)
        return 2
    token, _ = create_access_token(
        user_id=LECTURER_ID, role=Role.LECTURER, email=LECTURER_EMAIL, settings=settings
    )
    api = httpx.Client(base_url=f"{args.base}/api/v1", headers={"Authorization": f"Bearer {token}"})

    # The meeting routes sit behind the terms consent, as the session routes do.
    api.post("/auth/consent", json={"consent_type": "terms", "granted": True}).raise_for_status()

    if args.action == "link":
        if args.session_id is None:
            parser.error("link needs a session id")
        response = api.put(f"/meetings/{args.meeting_id}", json={"session_id": args.session_id})
    else:
        event = {"kind": "started" if args.action == "start" else "ended"}
        event |= {"meeting_id": args.meeting_id, "course_code": args.course, "title": args.title}
        response = api.post("/meetings/events", json=event)

    print(response.status_code, response.text)
    return 0 if response.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
