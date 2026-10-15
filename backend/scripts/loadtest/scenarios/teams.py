"""A Teams meeting, through the mock adapter.

See common.py for what a scenario returns.
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

import httpx

from scripts.loadtest.clients import Client, is_type
from scripts.loadtest.environment import COURSE_CODE, Person, Seeded, Server
from scripts.loadtest.scenarios.common import (
    Result,
    spread,
)

# -- 5. Teams, through the mock adapter ----------------------------------------------


async def teams_meeting(server: Server, seeded: Seeded, students: list[Person]) -> Result:
    result = Result("teams", "A Teams meeting through the mock adapter")
    lecturer = {"Authorization": f"Bearer {seeded.lecturer.token}"}
    async with httpx.AsyncClient(
        base_url=f"{server.base}/api/v1", headers=lecturer, timeout=30
    ) as http:
        created = await http.post(
            "/sessions", json={"course_code": COURSE_CODE, "title": "Teams class"}
        )
        session_id = UUID(created.json()["id"])
        meeting = "19:meeting_load_test@thread.v2"
        linked = await http.put(f"/meetings/{meeting}", json={"session_id": str(session_id)})
        result.check(
            "the meeting was linked to a prepared session",
            linked.status_code == 200,
            linked.text[:200],
        )

        clients = [Client(s, server.ws, session_id) for s in students]
        await asyncio.gather(*(c.connect() for c in clients))
        await asyncio.gather(*(c.wait_for(is_type("session.state"), 5.0) for c in clients))
        result.check(
            "students waiting in the meeting are told the session is prepared",
            all(c.of("session.state")[-1].data["status"] == "prepared" for c in clients),
        )

        asked = time.perf_counter()
        started = await http.post(
            "/meetings/events", json={"kind": "started", "meeting_id": meeting}
        )
        seen = await asyncio.gather(
            *(
                c.wait_for(lambda e: e.type == "session.state" and e.data["status"] == "active")
                for c in clients
            )
        )
        result.figures["meeting_start_to_last_student"] = spread([e.at - asked for e in seen])
        result.check(
            "the meeting starting started the session for everyone", started.status_code == 200
        )

        again = await http.post("/meetings/events", json={"kind": "started", "meeting_id": meeting})
        await asyncio.sleep(0.3)
        active = [
            len([e for e in c.of("session.state") if e.data["status"] == "active" and e.seq])
            for c in clients
        ]
        result.check(
            "the same event delivered twice changed nothing",
            again.status_code == 200 and again.json()["id"] == str(session_id) and max(active) == 1,
            active[:3],
        )

        ended = await http.post("/meetings/events", json={"kind": "ended", "meeting_id": meeting})
        await asyncio.gather(
            *(
                c.wait_for(lambda e: e.type == "session.state" and e.data["status"] == "ended")
                for c in clients
            )
        )
        result.check("the meeting ending ended the session for everyone", ended.status_code == 200)
        await asyncio.gather(*(c.close() for c in clients))

        unlinked = await http.post(
            "/meetings/events",
            json={
                "kind": "started",
                "meeting_id": "19:meeting_unlinked@thread.v2",
                "course_code": COURSE_CODE,
            },
        )
        made = unlinked.json()
        result.check(
            "a meeting with no session linked creates and starts one",
            unlinked.status_code == 200 and made.get("status") == "active",
            unlinked.text[:200],
        )
        if unlinked.status_code == 200:
            await http.post(f"/sessions/{made['id']}/end")

    async with httpx.AsyncClient(base_url=f"{server.base}/api/v1", timeout=30) as anyone:
        real = await anyone.post("/teams/messages", json={"type": "event"})
        result.check(
            "the real Teams adapter answers 503 while no Teams credentials are set",
            real.status_code == 503,
            real.status_code,
        )
    return result
