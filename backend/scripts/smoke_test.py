"""Check a running demo deployment from the outside, through its proxy.

    python scripts/smoke_test.py --base http://localhost:8088
    python scripts/smoke_test.py --base http://localhost:8088 --idle 90

Needs only httpx and websockets, so it runs from any Python with the backend's
dependencies and does not import the app. It prints one line per check and
exits 1 if any failed. The accounts are the development ones listed in the
README, so it is meant for a deployment started with CLIP_ENV=development.

The socket check goes through the same proxy as a browser would. It stays
open and idle for --idle seconds, so a proxy timeout shorter than the server's
own pings would show up here as a close.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from typing import Any

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

# Development accounts from the README ("Demo Accounts").
LECTURER = ("lecturer@clip.example.com", "LecturerPass123!")
STUDENT = ("student@clip.example.com", "StudentPass123!")

# Longest to wait for one reply from the server.
REPLY_TIMEOUT_SECONDS = 10.0

failures = 0


def report(name: str, ok: bool, detail: str = "") -> bool:
    """Print one line for a check and remember if it failed."""
    global failures
    if not ok:
        failures += 1
    suffix = f" ({detail})" if detail else ""
    print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")
    return ok


def check(name: str, test: Callable[[], str | None]) -> bool:
    """Run a test that returns None on success, or a reason on failure."""
    try:
        reason = test()
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    return report(name, reason is None, reason or "")


def login(api: httpx.Client, email: str, password: str) -> str | None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        return None
    token = response.json().get("access_token")
    return token if isinstance(token, str) else None


async def socket_check(base: str, token: str, idle_seconds: float) -> None:
    """Authenticate, ping, sit idle, ping again, all on one connection."""
    url = base.replace("http", "ws", 1) + "/ws/session"
    name = "websocket via proxy"
    try:
        # No client keepalive: only the server's own pings may hold the socket
        # open, as they do for a browser, which sends none.
        async with connect(url, ping_interval=None, open_timeout=10) as socket:

            async def next_event() -> dict[str, Any]:
                raw = await asyncio.wait_for(socket.recv(), REPLY_TIMEOUT_SECONDS)
                event = json.loads(raw)
                return event if isinstance(event, dict) else {}

            await socket.send(json.dumps({"type": "auth", "data": {"token": token}}))
            ready = await next_event()
            report(f"{name}: auth gets ready", ready.get("type") == "ready", str(ready.get("type")))

            await socket.send(json.dumps({"type": "ping", "data": {}}))
            pong = await next_event()
            report(f"{name}: ping gets pong", pong.get("type") == "pong", str(pong.get("type")))

            try:
                # Anything the server sends meanwhile is ignored. Only a close fails.
                async with asyncio.timeout(idle_seconds):
                    while True:
                        await socket.recv()
            except TimeoutError:
                pass
            except ConnectionClosed as closed:
                report(f"{name}: open {idle_seconds:g}s idle", False, f"closed {closed.rcvd}")
                return

            await socket.send(json.dumps({"type": "ping", "data": {}}))
            again = await next_event()
            report(
                f"{name}: open {idle_seconds:g}s idle",
                again.get("type") == "pong",
                str(again.get("type")),
            )
    except (OSError, TimeoutError, InvalidStatus, ConnectionClosed) as exc:
        report(name, False, f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://localhost:8088", help="the proxy's address")
    parser.add_argument(
        "--idle", type=float, default=25.0, help="seconds the socket sits idle (default 25)"
    )
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")

    api = httpx.Client(base_url=base, timeout=15.0)

    def health() -> str | None:
        response = api.get("/api/v1/health")
        return None if response.status_code == 200 else f"status {response.status_code}"

    def ready() -> str | None:
        response = api.get("/api/v1/ready")
        postgres = [d for d in response.json()["dependencies"] if d["name"] == "postgres"]
        if response.status_code != 200 or not postgres or not postgres[0]["ok"]:
            return f"status {response.status_code}, postgres {postgres}"
        return None

    def index() -> str | None:
        response = api.get("/")
        if response.status_code != 200 or 'id="root"' not in response.text:
            return f"status {response.status_code}, not the SPA index"
        return None

    def deep_link() -> str | None:
        response = api.get("/login")
        home = api.get("/")
        if response.status_code != 200 or response.text != home.text:
            return f"status {response.status_code}, not the SPA index"
        return None

    def unauthenticated() -> str | None:
        response = api.get("/api/v1/auth/me")
        body = response.json()
        if response.status_code != 401 or "code" not in body.get("error", {}):
            return f"status {response.status_code}, body {body}"
        if not response.headers.get("X-Request-ID"):
            return "no X-Request-ID on the response"
        return None

    check("GET /api/v1/health", health)
    check("GET /api/v1/ready reports postgres ok", ready)
    check("GET / serves the SPA", index)
    check("GET /login falls back to the SPA", deep_link)
    check("unauthenticated call gets a 401 JSON error", unauthenticated)

    tokens: dict[str, str] = {}
    for role, (email, password) in {"lecturer": LECTURER, "student": STUDENT}.items():
        token = login(api, email, password)
        if report(f"login as demo {role}", token is not None) and token:
            tokens[role] = token
            consent = api.post(
                "/api/v1/auth/consent",
                json={"consent_type": "terms", "granted": True},
                headers={"Authorization": f"Bearer {token}"},
            )
            report(
                f"terms consent as demo {role}",
                consent.status_code == 201,
                str(consent.status_code),
            )

    if "student" in tokens:
        asyncio.run(socket_check(base, tokens["student"], args.idle))
    else:
        report("websocket via proxy", False, "no student token")

    print(f"\n{failures} failed" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
