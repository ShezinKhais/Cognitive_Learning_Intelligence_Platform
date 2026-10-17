"""What a load run does to the server, and what it checks afterwards.

Every scenario returns a Result: the figures it measured and the checks it
made. A check is something that has to be true for the system to be working,
such as "nobody's stream has a gap". A figure is how long something took,
reported and not judged, except where a limit is stated.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select

from scripts.loadtest.clients import Client, is_type
from scripts.loadtest.environment import COURSE_CODE, Database, Person, Seeded, Server, sessions

# Limits a healthy run stays inside on one machine. Generous: they catch a
# system that has stopped working, not one that is a little slow today.
FAN_OUT_LIMIT_SECONDS = 2.0
RECEIPT_LIMIT_SECONDS = 2.0
CONNECT_LIMIT_SECONDS = 10.0
RECONNECT_LIMIT_SECONDS = 10.0


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Result:
    name: str
    title: str
    figures: dict[str, Any] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.ok for check in self.checks)

    def check(self, name: str, ok: bool, detail: object = "") -> bool:
        self.checks.append(Check(name, bool(ok), str(detail)))
        return bool(ok)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "passed": self.passed,
            "figures": self.figures,
            "checks": [check.__dict__ for check in self.checks],
            "notes": self.notes,
        }


def spread(values: list[float]) -> dict[str, float]:
    """Median, 95th percentile and worst of some timings, in milliseconds."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def at(share: float) -> float:
        return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]

    return {
        "count": len(ordered),
        "p50_ms": round(at(0.50) * 1000, 1),
        "p95_ms": round(at(0.95) * 1000, 1),
        "max_ms": round(ordered[-1] * 1000, 1),
    }


class Classroom:
    """One session with its lecturer's panel and its students connected."""

    def __init__(self, server: Server, database: Database, seeded: Seeded) -> None:
        self.server = server
        self.database = database
        self.seeded = seeded
        self.session_id: UUID | None = None
        self.students: list[Client] = []
        self.panel: Client | None = None
        self.delivered = 0
        # For every question delivered so far: how long the lecturer's request
        # took to answer, and each student's wait from the server stamping the
        # question to it arriving.
        self._http: dict[UUID, httpx.AsyncClient] = {}
        self.request_seconds: list[float] = []
        self.transit: list[float] = []
        self.rng = random.Random(321)

    @contextlib.asynccontextmanager
    async def http(self, who: Person | None = None) -> AsyncIterator[httpx.AsyncClient]:
        """The person's HTTP client, kept open between requests as a browser
        keeps its connection. Making a new one each time costs a third of a
        second on its own, which would be measured as the server's."""
        who = who or self.seeded.lecturer
        client = self._http.get(who.user_id)
        if client is None:
            client = self._http[who.user_id] = httpx.AsyncClient(
                base_url=f"{self.server.base}/api/v1",
                headers={"Authorization": f"Bearer {who.token}"},
                timeout=30.0,
            )
        yield client

    async def forget_connections(self) -> None:
        """Drop the kept HTTP connections, as after the server has restarted."""
        clients, self._http = list(self._http.values()), {}
        await asyncio.gather(*(c.aclose() for c in clients))

    async def open(self, students: list[Person], title: str = "Load test class") -> None:
        async with self.http() as http:
            created = await http.post(
                "/sessions", json={"course_code": COURSE_CODE, "title": title}
            )
            created.raise_for_status()
            self.session_id = UUID(created.json()["id"])
            (await http.post(f"/sessions/{self.session_id}/start")).raise_for_status()
        self.panel = Client(self.seeded.lecturer, self.server.ws, self.session_id)
        await self.panel.connect()
        self.students = [Client(s, self.server.ws, self.session_id) for s in students]
        await asyncio.gather(*(s.connect() for s in self.students))

    async def close(self) -> None:
        await self.forget_connections()
        await asyncio.gather(
            *(s.close() for s in self.students), *([self.panel.close()] if self.panel else [])
        )

    async def end(self) -> None:
        if self.session_id is not None:
            async with self.http() as http:
                await http.post(f"/sessions/{self.session_id}/end")

    async def deliver(self, expect: list[Client] | None = None) -> tuple[str, list[float], float]:
        """Deliver the next staged question and wait for it to reach every
        connected student. Returns its id, each student's seconds from the
        lecturer's request to the question arriving, and when it was asked."""
        question_id = str(self.seeded.questions.pop(0))
        expect = self.students if expect is None else expect
        asked = time.perf_counter()
        async with self.http() as http:
            response = await http.post(
                f"/sessions/{self.session_id}/questions/{question_id}:deliver"
            )
            response.raise_for_status()
        self.request_seconds.append(time.perf_counter() - asked)
        arrived = await asyncio.gather(
            *(s.wait_for(is_type("question.delivered", question_id=question_id)) for s in expect)
        )
        self.transit += [event.transit for event in arrived]
        self.delivered += 1
        return question_id, [event.at - asked for event in arrived], asked

    async def answer_all(
        self, question_id: str, who: list[Client] | None = None
    ) -> list[float | None]:
        """Every student answers after thinking for a moment of their own."""

        async def one(student: Client) -> float | None:
            await asyncio.sleep(self.rng.uniform(0.05, 0.8))
            return await student.answer(question_id)

        return await asyncio.gather(*(one(s) for s in (who or self.students)))

    async def closed(self, question_id: str, timeout: float = 30.0) -> dict[str, Any]:  # noqa: ASYNC109
        assert self.panel is not None
        event = await self.panel.wait_for(
            is_type("question.closed", question_id=question_id), timeout
        )
        return event.data

    def gaps(self) -> list[str]:
        clients = [*self.students, *([self.panel] if self.panel else [])]
        return [f"{c.person.email}: {gap}" for c in clients for gap in c.gaps]

    async def stored(self, model: Any) -> int:
        async with sessions(self.database)() as db:
            return (
                await db.execute(
                    select(func.count())
                    .select_from(model)
                    .where(model.session_id == self.session_id)
                )
            ).scalar_one()
