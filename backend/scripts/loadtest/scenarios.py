"""What a load run does to the server, and what it checks afterwards.

Every scenario returns a Result: the figures it measured and the checks it
made. A check is something that has to be true for the system to be working,
such as "nobody's stream has a gap". A figure is how long something took,
reported and not judged, except where a limit is stated.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import subprocess
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select

from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.delivered_question import DeliveredQuestion
from app.models.student_response import StudentResponse
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


# -- 1. forty students, and questions ------------------------------------------------


async def class_under_load(room: Classroom, students: list[Person], rounds: int) -> Result:
    result = Result("class", f"{len(students)} students in one class, {rounds} questions")
    began = time.perf_counter()
    await room.open(students)
    result.figures["connect_all_seconds"] = round(time.perf_counter() - began, 2)
    result.figures["time_to_ready"] = spread([s.ready_seconds or 0.0 for s in room.students])
    told = await asyncio.gather(
        *(s.wait_for(is_type("session.state"), 5.0) for s in room.students), return_exceptions=True
    )
    result.check(
        "every student connected and was told the session's state",
        all(s.connected for s in room.students) and not any(isinstance(t, Exception) for t in told),
    )
    result.check(
        f"all connected inside {CONNECT_LIMIT_SECONDS:.0f} s",
        result.figures["connect_all_seconds"] <= CONNECT_LIMIT_SECONDS,
        f"{result.figures['connect_all_seconds']} s",
    )
    assert room.panel is not None
    counts = [e.data["participant_count"] for e in room.panel.of("session.state")]
    await asyncio.sleep(0.3)
    counts = [e.data["participant_count"] for e in room.panel.of("session.state")]
    result.check(
        "the lecturer's panel counts every student once",
        bool(counts) and counts[-1] == len(students),
        f"last count {counts[-1] if counts else None}",
    )

    fan_out: list[float] = []
    width: list[float] = []
    receipts: list[float] = []
    refused = 0
    short = []
    for _ in range(rounds):
        question_id, arrivals, _ = await room.deliver()
        fan_out += arrivals
        width.append(max(arrivals) - min(arrivals))
        took = await room.answer_all(question_id)
        refused += sum(1 for t in took if t is None)
        receipts += [t for t in took if t is not None]
        closed = await room.closed(question_id)
        if closed["respondents"] != len(students) or closed["eligible"] != len(students):
            short.append(closed)
    result.figures["question_fan_out"] = spread(fan_out)
    result.figures["of_which_server_to_student"] = spread(room.transit)
    result.figures["of_which_the_lecturers_request"] = spread(room.request_seconds)
    result.figures["fan_out_first_to_last_student"] = spread(width)
    result.figures["answer_to_receipt"] = spread(receipts)
    result.check("every answer was accepted", refused == 0, f"{refused} refused")
    result.check(
        "every question closed with every student counted as shown and answered",
        not short,
        short[:2],
    )
    result.check(
        f"the slowest question reached its last student inside {FAN_OUT_LIMIT_SECONDS:.0f} s",
        max(fan_out) <= FAN_OUT_LIMIT_SECONDS,
        f"{max(fan_out) * 1000:.0f} ms",
    )
    result.check(
        f"the slowest receipt came back inside {RECEIPT_LIMIT_SECONDS:.0f} s",
        bool(receipts) and max(receipts) <= RECEIPT_LIMIT_SECONDS,
        f"{max(receipts) * 1000:.0f} ms" if receipts else "none",
    )
    stored = await room.stored(StudentResponse)
    result.check(
        "every answer is in the database",
        stored == rounds * len(students),
        f"{stored} of {rounds * len(students)}",
    )
    result.check("no client saw a gap or a repeat in its stream", not room.gaps(), room.gaps()[:3])
    return result


# -- 2. reconnecting -----------------------------------------------------------------


async def reconnecting(room: Classroom) -> Result:
    result = Result("reconnect", "Dropped connections, resumed")
    half = room.students[: len(room.students) // 2]
    rest = room.students[len(half) :]
    cursors = {id(s): s.last_seq for s in half}
    await asyncio.gather(*(s.drop() for s in half))

    # While they are away: one whole question, and another left open.
    missed, _, _ = await room.deliver(expect=rest)
    await room.answer_all(missed, rest)
    await room.closed(missed)
    open_id, _, _ = await room.deliver(expect=rest)

    began = time.perf_counter()
    await asyncio.gather(*(s.connect(resume=True) for s in half))
    result.figures["half_class_resume_seconds"] = round(time.perf_counter() - began, 2)
    result.check(
        "every returning student was resumed from the cursor it offered",
        all(s.resumed_from == cursors[id(s)] for s in half),
        [(s.resumed_from, cursors[id(s)]) for s in half if s.resumed_from != cursors[id(s)]][:3],
    )
    await asyncio.gather(
        *(s.wait_for(is_type("question.delivered", question_id=open_id)) for s in half)
    )
    replayed = [
        all(
            s.of(kind) and any(e.data.get("question_id") == missed for e in s.of(kind))
            for kind in ("question.delivered", "question.closed")
        )
        for s in half
    ]
    result.check("the question they missed was replayed to each, delivery and close", all(replayed))
    result.check("the replay left no gap and repeated nothing", not room.gaps(), room.gaps()[:3])
    took = await room.answer_all(open_id, half)
    result.check(
        "each could answer the question that was open when they came back",
        all(t is not None for t in took),
    )
    await room.answer_all(open_id, rest)
    closed = await room.closed(open_id)
    result.check(
        "that question closed with the whole class counted",
        closed["respondents"] == len(room.students),
        closed,
    )

    # Everyone at once, as when a building's network blinks.
    await asyncio.gather(*(s.drop() for s in room.students))
    before = {id(s): s.last_seq for s in room.students}
    began = time.perf_counter()
    await asyncio.gather(*(s.connect(resume=True) for s in room.students))
    storm = time.perf_counter() - began
    result.figures["whole_class_reconnect_seconds"] = round(storm, 2)
    result.figures["reconnect_time_to_ready"] = spread(
        [s.ready_seconds or 0.0 for s in room.students]
    )
    result.check(
        f"the whole class was back inside {RECONNECT_LIMIT_SECONDS:.0f} s",
        storm <= RECONNECT_LIMIT_SECONDS,
        f"{storm:.2f} s",
    )
    wrong = [
        (s.resumed_from, before[id(s)]) for s in room.students if s.resumed_from != before[id(s)]
    ]
    result.check(
        "all were resumed from the cursor they offered, with no gap",
        not wrong and not room.gaps(),
        wrong[:3],
    )
    assert room.panel is not None
    await asyncio.sleep(0.5)
    count = room.panel.of("session.state")[-1].data["participant_count"]
    result.check(
        "the panel's count returned to the whole class", count == len(room.students), count
    )

    # A cursor from a stream the server no longer has must not be honoured.
    stranger = room.students[0]
    await stranger.drop()
    stranger.stream_id = "00000000-0000-4000-8000-000000000000"
    await stranger.connect(resume=True)
    result.check(
        "a cursor from another stream is refused, and the client starts afresh",
        stranger.resumed_from is None and bool(stranger.of("session.state")),
    )
    question_id, arrivals, _ = await room.deliver()
    await room.answer_all(question_id)
    await room.closed(question_id)
    result.figures["fan_out_after_reconnects"] = spread(arrivals)
    return result


# -- 3. attention signals and breakout rooms ----------------------------------------


async def signals_and_rooms(room: Classroom, seconds: float, every: float) -> Result:
    result = Result("signals", "Attention signals and breakout rooms under load")
    assert room.panel is not None
    students = room.students
    rooms = 8
    for index, student in enumerate(students):
        await student.send("room.confirm", {"room_label": f"Room {index % rooms + 1}"})
    await asyncio.sleep(0.5)
    seen_before = len(room.panel.events)

    # The first half of the rooms talk; the second half never do. In every
    # room, the odd-numbered students are looking away with no face in view.
    async def report(index: int, student: Client) -> int:
        sent = 0
        talking = (index % rooms) < rooms // 2
        away = index % 2 == 1
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            await student.send(
                "signal.attention",
                {
                    "gaze_on_screen_ratio": 0.05 if away else 0.95,
                    "face_present": not away,
                    # One member of a talking room always is, so the room is
                    # never silent by chance: only one reading per student
                    # every two seconds is kept.
                    "speaking": talking and (index < rooms or room.rng.random() < 0.5),
                    "window_seconds": 5.0,
                },
            )
            sent += 1
            await asyncio.sleep(every)
        return sent

    reporting = asyncio.gather(*(report(i, s) for i, s in enumerate(students)))
    await asyncio.sleep(seconds / 2)
    question_id, arrivals, _ = await room.deliver()
    await room.answer_all(question_id)
    await room.closed(question_id)
    sent = sum(await reporting)
    # How the rooms stood as the signals stopped. After that every room falls
    # silent, so a talking room is judged here and not a moment later.
    while_talking = len(room.panel.events)
    await asyncio.sleep(1.5)

    result.figures["signals_sent"] = sent
    result.figures["signals_per_second"] = round(sent / seconds, 1)
    result.figures["fan_out_while_signalling"] = spread(arrivals)
    result.check(
        f"a question still reached everyone inside {FAN_OUT_LIMIT_SECONDS:.0f} s",
        max(arrivals) <= FAN_OUT_LIMIT_SECONDS,
        f"{max(arrivals) * 1000:.0f} ms",
    )
    errors = [e.data for s in students for e in s.of("error")]
    result.check("no signal was refused or throttled", not errors, errors[:3])

    panel = room.panel.events[seen_before:]
    statuses: dict[str, str] = {}
    for event in room.panel.of("room.status"):
        statuses[event.data["room_label"]] = event.data["status"]
    talked: dict[str, str] = {}
    for event in room.panel.events[:while_talking]:
        if event.type == "room.status":
            talked[event.data["room_label"]] = event.data["status"]
    quiet = [f"Room {n}" for n in range(rooms // 2 + 1, rooms + 1)]
    talking = [f"Room {n}" for n in range(1, rooms // 2 + 1)]
    result.figures["room_status_events"] = len([e for e in panel if e.type == "room.status"])
    result.check("the panel was told about every room", len(statuses) == rooms, sorted(statuses))
    result.check(
        "the rooms that talked are active",
        all(talked.get(r) == "active" for r in talking),
        talked,
    )
    result.check(
        "the rooms that never talked came to need attention",
        all(statuses.get(r) == "needs_attention" for r in quiet),
        statuses,
    )
    alerts = [
        e.data for e in panel if e.type == "alert.raised" and e.data["kind"] == "breakout_inactive"
    ]
    result.check(
        "each silent room raised one alert, and no other room did",
        len(alerts) == len(quiet) and all(any(r in a["message"] for a in alerts) for r in quiet),
        [a["message"] for a in alerts],
    )
    leaked = [s.person.email for s in students if s.of("room.status") or s.of("alert.raised")]
    result.check("no student was sent a room's status or an alert", not leaked, leaked[:3])

    prompted = {
        index: [e for e in s.of("prompt.attention") if "still with the class" in e.data["message"]]
        for index, s in enumerate(students)
    }
    away = [i for i in prompted if i % 2 == 1]
    result.figures["refocus_prompts"] = sum(len(p) for p in prompted.values())
    result.check(
        "every student who was looking away got one private prompt",
        all(len(prompted[i]) == 1 for i in away),
        {i: len(prompted[i]) for i in away if len(prompted[i]) != 1},
    )
    result.check(
        "no student who was looking at the screen was prompted",
        all(not prompted[i] for i in prompted if i % 2 == 0),
    )

    async with room.http() as http:
        engagement = (await http.get(f"/sessions/{room.session_id}/engagement")).json()
    result.check(
        "engagement is reported for every student",
        len(engagement) == len(students),
        len(engagement),
    )
    # A minute is stored once a signal arrives in the next one. Keep every
    # student signalling, slowly, until that has happened for all of them.
    kept = await room.stored(AttentionSignalSummary)
    deadline = time.perf_counter() + 75
    while kept < len(students) and time.perf_counter() < deadline:
        for student in students:
            await student.send(
                "signal.attention",
                {"gaze_on_screen_ratio": 0.9, "face_present": True, "window_seconds": 5.0},
            )
        await asyncio.sleep(2.5)
        kept = await room.stored(AttentionSignalSummary)
    result.figures["attention_minutes_stored"] = kept
    result.check(
        "a minute of attention reached the analytics table for every student",
        kept >= len(students),
        kept,
    )
    result.check("no gap in any stream", not room.gaps(), room.gaps()[:3])
    return result


# -- 4. reports and the purge, during a class ------------------------------------------


async def housekeeping_during_class(room: Classroom, baseline: dict[str, float]) -> Result:
    result = Result("housekeeping", "Reports and the retention purge during a class")
    purge_lines = len(room.server.purge_lines())
    async with room.http() as http:
        asked = [await http.post(f"/sessions/{room.session_id}/reports") for _ in range(2)]
        result.check("the report was accepted at once", all(r.status_code == 202 for r in asked))
        result.check(
            "asking again while it is built returns the same report",
            len({r.json().get("report_id") for r in asked}) == 1,
            [r.text[:120] for r in asked],
        )

        arrivals: list[float] = []
        for _ in range(3):
            question_id, took, _ = await room.deliver()
            arrivals += took
            await room.answer_all(question_id)
            await room.closed(question_id)
        result.figures["fan_out_with_reports_building"] = spread(arrivals)
        result.figures["fan_out_baseline"] = baseline
        result.check(
            f"questions still reached everyone inside {FAN_OUT_LIMIT_SECONDS:.0f} s",
            max(arrivals) <= FAN_OUT_LIMIT_SECONDS,
            f"{max(arrivals) * 1000:.0f} ms",
        )

        report_id = asked[0].json()["report_id"]
        for _ in range(100):
            status = await http.get(f"/reports/{report_id}")
            job = status.json()
            if job["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.1)
        result.check(
            "the report became ready",
            job["status"] == "ready",
            (job["status"], job.get("error"), job.get("message")),
        )
        report = job.get("report") or {}
        delivered = report.get("participation", {}).get("questions_delivered", 0)
        result.check(
            "the report counts the questions delivered when it was asked for",
            delivered >= room.delivered - 3,
            delivered,
        )
        emails = [s.email for s in room.seeded.students if s.email in status.text]
        ids = [str(s.user_id) for s in room.seeded.students if str(s.user_id) in status.text]
        result.check("the report names no student", not emails and not ids, (emails[:2], ids[:2]))
        pdf = await http.get(f"/reports/{report_id}/pdf")
        result.figures["report_pdf_bytes"] = len(pdf.content)
        result.check(
            "the PDF downloads",
            pdf.status_code == 200 and pdf.content.startswith(b"%PDF"),
            (pdf.status_code, pdf.headers.get("content-type")),
        )

    # The server runs the purge every few seconds in this test. Every run
    # while the class was on must have stopped at once and deleted nothing.
    runs = room.server.purge_lines()[purge_lines:]
    result.figures["purge_runs_during_class"] = len(runs)
    result.check("the purge ran while the class did", bool(runs))
    result.check(
        "every purge during the class gave way to it and deleted nothing",
        all("deleted 0 item" in line and "stopped early" in line for line in runs),
        runs[:2],
    )
    return result


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


# -- 6. the model is down -------------------------------------------------------------


async def model_down(room: Classroom) -> Result:
    result = Result("model", "The language model is unreachable")
    student = room.students[0]
    took: list[float] = []
    ends: list[str] = []
    async with room.http(student.person) as http:
        for attempt in range(4):
            began = time.perf_counter()
            response = await http.post(
                f"/sessions/{room.session_id}/chat",
                json={
                    "request_id": f"load-{attempt}",
                    "question": "Why are the base layers frozen?",
                },
            )
            took.append(time.perf_counter() - began)
            lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
            ends.append(
                lines[-1]["type"]
                if response.status_code == 200 and lines
                else str(response.status_code)
            )
    result.figures["chat_time_to_failure"] = spread(took)
    result.figures["chat_endings"] = ends
    result.check(
        "the tutor answered each question with a plain failure and no hang",
        all(end in ("error", "empty_retrieval", "503") for end in ends) and max(took) < 15,
        ends,
    )
    question_id, arrivals, _ = await room.deliver()
    await room.answer_all(question_id)
    closed = await room.closed(question_id)
    result.figures["fan_out_with_model_down"] = spread(arrivals)
    result.check(
        "questions still go out and are answered with the model down",
        closed["respondents"] == len(room.students) and max(arrivals) <= FAN_OUT_LIMIT_SECONDS,
        closed,
    )
    async with httpx.AsyncClient(base_url=f"{room.server.base}/api/v1", timeout=10) as anyone:
        ready = await anyone.get("/ready")
    model = next((d for d in ready.json().get("dependencies", []) if d["name"] == "ollama"), {})
    result.check("readiness reports the model as down", model.get("ok") is False, ready.text[:200])
    return result


# -- 7. the server dies ---------------------------------------------------------------


async def server_crash(room: Classroom) -> Result:
    result = Result("crash", "The server is killed mid-question and restarted")
    server = room.server
    abandoned, _, _ = await room.deliver()
    delivered_before = room.delivered
    clients = [*room.students, room.panel]
    assert room.panel is not None

    began = time.perf_counter()
    await server.kill()
    for client in clients:
        for _ in range(100):
            if not client.connected:
                break
            await asyncio.sleep(0.05)
    result.figures["clients_noticed_seconds"] = round(time.perf_counter() - began, 2)
    result.check(
        "every client noticed the connection had gone", all(not c.connected for c in clients)
    )

    result.figures["restart_to_healthy_seconds"] = round(await server.start(), 2)
    await room.forget_connections()
    began = time.perf_counter()
    await asyncio.gather(*(c.connect(resume=True) for c in clients))
    result.figures["whole_class_back_seconds"] = round(time.perf_counter() - began, 2)
    result.check(
        "no cursor from before the crash was honoured",
        all(c.resumed_from is None for c in clients),
        "a restarted server numbers its stream again, so an old cursor must not match",
    )
    await asyncio.sleep(0.5)
    states = [c.of("session.state")[-1].data for c in room.students]
    wrong = [
        s for s in states if s["status"] != "active" or s["questions_delivered"] != delivered_before
    ]
    result.check(
        "the session came back active, with its count of questions intact",
        not wrong,
        f"expected {delivered_before} delivered; {len(wrong)} differ, such as {wrong[:2]}",
    )
    result.check(
        "the question that was open is not offered again",
        all(s["active_question_id"] is None for s in states),
    )
    late = await room.students[0].answer(abandoned)
    result.check("an answer to the abandoned question is refused, with a receipt", late is None)

    question_id, arrivals, _ = await room.deliver()
    took = await room.answer_all(question_id)
    closed = await room.closed(question_id)
    result.figures["fan_out_after_restart"] = spread(arrivals)
    result.check(
        "the next question reached and was answered by the whole class",
        closed["respondents"] == len(room.students) and all(t is not None for t in took),
        closed,
    )
    async with sessions(room.database)() as db:
        unfinished = (
            await db.execute(
                select(func.count())
                .select_from(DeliveredQuestion)
                .where(
                    DeliveredQuestion.session_id == room.session_id,
                    DeliveredQuestion.closed_at.is_(None),
                )
            )
        ).scalar_one()
    result.figures["deliveries_left_unclosed_by_the_crash"] = unfinished
    result.notes.append(
        "The question open at the crash has no recorded close. Readers treat a delivery "
        "whose closes_at has passed as closed by a restart, respondents unknown."
    )
    return result


# -- 8. a planned restart -------------------------------------------------------------


async def planned_restart(room: Classroom) -> Result:
    result = Result("restart", "A planned shutdown and restart during a class")
    server = room.server
    clients = [*room.students, room.panel]
    assert room.panel is not None
    result.figures["shutdown_seconds"] = round(await server.stop(), 2)
    for client in clients:
        for _ in range(100):
            if not client.connected:
                break
            await asyncio.sleep(0.05)
    codes = sorted({c.close_code for c in clients if c.close_code is not None})
    result.figures["close_codes_seen"] = codes
    result.check(
        "every client was disconnected by the shutdown", all(not c.connected for c in clients)
    )
    result.figures["restart_to_healthy_seconds"] = round(await server.start(), 2)
    await room.forget_connections()
    began = time.perf_counter()
    await asyncio.gather(*(c.connect(resume=True) for c in clients))
    result.figures["whole_class_back_seconds"] = round(time.perf_counter() - began, 2)
    question_id, arrivals, _ = await room.deliver()
    took = await room.answer_all(question_id)
    closed = await room.closed(question_id)
    result.figures["fan_out_after_restart"] = spread(arrivals)
    result.check(
        "the class carried on: the next question was answered by everyone",
        closed["respondents"] == len(room.students) and all(t is not None for t in took),
        closed,
    )
    return result


# -- 9. the database goes away ----------------------------------------------------------


async def database_outage(room: Classroom, container: str, seconds: float) -> Result:
    result = Result("database", f"The database is stopped for {seconds:.0f} s during a class")
    server = room.server
    assert room.panel is not None
    clients = [*room.students, room.panel]

    def docker(*args: str) -> None:
        subprocess.run(["docker", *args], check=True, capture_output=True, timeout=120)

    stopped_at = datetime.now()
    await asyncio.to_thread(docker, "stop", container)
    try:
        began = time.perf_counter()
        async with httpx.AsyncClient(base_url=f"{server.base}/api/v1", timeout=30) as anyone:
            ready = await anyone.get("/ready")
            health = await anyone.get("/health")
        result.figures["readiness_answered_in_seconds"] = round(time.perf_counter() - began, 2)
        result.check(
            "readiness says the server is not ready", ready.status_code == 503, ready.status_code
        )
        result.check("liveness still answers", health.status_code == 200, health.status_code)

        question_id = str(room.seeded.questions[0])
        began = time.perf_counter()
        async with room.http() as http:
            refused = await http.post(
                f"/sessions/{room.session_id}/questions/{question_id}:deliver"
            )
        result.figures["delivery_refused_in_seconds"] = round(time.perf_counter() - began, 2)
        result.check(
            "a delivery is refused with an error and not left hanging",
            refused.status_code >= 500 and "error" in refused.text,
            f"{refused.status_code} {refused.text[:120]}",
        )
        await asyncio.sleep(max(seconds - (time.perf_counter() - began), 0))
        result.check(
            "no socket was dropped while the database was away",
            all(c.connected for c in clients),
            sum(1 for c in clients if not c.connected),
        )
        late = Client(room.seeded.students[0], server.ws, room.session_id)
        try:
            await late.connect()
            result.check(
                "a new connection is turned away during the outage", False, "it was admitted"
            )
        except Exception as exc:
            result.check(
                "a new connection is turned away during the outage, to try again",
                late.close_code in (None, 1013) or "1013" in str(exc),
                f"{type(exc).__name__} {exc}"[:160],
            )
        finally:
            await late.close()
    finally:
        await asyncio.to_thread(docker, "start", container)

    began = time.perf_counter()
    async with httpx.AsyncClient(base_url=f"{server.base}/api/v1", timeout=30) as anyone:
        for _ in range(240):
            try:
                if (await anyone.get("/ready")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    result.figures["ready_again_after_seconds"] = round(time.perf_counter() - began, 2)
    # Requests that reached the server while it could not reach the database
    # failed as they should, and logged why. Only those are excused.
    server.outages.append((stopped_at, datetime.now()))
    result.figures["errors_logged_during_outage"] = len(server.log_errors()[1])
    question_id, arrivals, _ = await room.deliver()
    took = await room.answer_all(question_id)
    closed = await room.closed(question_id)
    result.figures["fan_out_after_recovery"] = spread(arrivals)
    result.check(
        "with the database back, a question reached and was answered by everyone",
        closed["respondents"] == len(room.students) and all(t is not None for t in took),
        closed,
    )
    result.check("no stream had a gap across the outage", not room.gaps(), room.gaps()[:3])
    return result


# -- 10. many sessions on the scheduler -----------------------------------------------


async def scheduler_load(
    server: Server,
    database: Database,
    seeded: Seeded,
    students: list[Person],
    classes: int,
    seconds: float,
    cycle: float,
) -> Result:
    """Several sessions at once, each with the question cycle on: the server
    sends every question itself, on its own timers."""
    result = Result("scheduler", f"{classes} sessions at once on the automatic question cycle")
    per_class = len(students) // classes
    answered: list[asyncio.Task[Any]] = []

    async def take_part(student: Client) -> None:
        seen = 0
        while True:
            delivered = student.of("question.delivered")
            for event in delivered[seen:]:
                await student.answer(event.data["question_id"])
            seen = len(delivered)
            await asyncio.sleep(0.05)

    rooms = []
    for index in range(classes):
        room = Classroom(server, database, seeded)
        room.rng = random.Random(index)
        await room.open(
            students[index * per_class : (index + 1) * per_class], f"Cycle class {index}"
        )
        # Answering from the moment the class is open: its first question is
        # due two seconds later, whether or not the other classes are ready.
        answered += [asyncio.create_task(take_part(s)) for s in room.students]
        rooms.append(room)

    await asyncio.sleep(seconds)
    stopped = time.perf_counter()
    for task in answered:
        task.cancel()
    await asyncio.gather(*answered, return_exceptions=True)

    gaps: list[float] = []
    counts = []
    short = 0
    for room in rooms:
        assert room.panel is not None
        delivered = room.panel.of("question.delivered")
        counts.append(len(delivered))
        gaps += [b.at - a.at for a, b in zip(delivered, delivered[1:], strict=False)]
        # A question still open when the students stopped answering is not
        # one the class failed to answer.
        whole = {e.data["question_id"] for e in delivered if e.at < stopped - cycle}
        short += sum(
            1
            for e in room.panel.of("question.closed")
            if e.data["question_id"] in whole and e.data["respondents"] != len(room.students)
        )
    expected = int(seconds // cycle)
    result.figures["questions_per_session"] = {"fewest": min(counts), "most": max(counts)}
    result.figures["expected_per_session"] = f"about {expected}"
    ordered = sorted(gaps)
    result.figures["seconds_between_questions"] = {
        "count": len(ordered),
        "p50": round(ordered[len(ordered) // 2], 2) if ordered else None,
        "max": round(ordered[-1], 2) if ordered else None,
    }
    result.figures["seconds_between_questions_expected"] = cycle
    result.check(
        "every session kept its own cycle going",
        min(counts) >= max(expected - 2, 1),
        counts,
    )
    late = max(gaps) - cycle if gaps else 0.0
    result.figures["worst_lateness_seconds"] = round(late, 2)
    result.check("no question was more than a second late", late <= 1.0, f"{late:.2f} s")
    result.check("every question closed with its whole class answered", short == 0, short)
    all_gaps = [gap for room in rooms for gap in room.gaps()]
    result.check("no stream had a gap", not all_gaps, all_gaps[:3])
    for room in rooms:
        await room.end()
        await room.close()
    return result
