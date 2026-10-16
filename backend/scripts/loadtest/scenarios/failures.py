"""What breaks: the model, the server, a planned restart and the database.

See common.py for what a scenario returns.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import datetime

import httpx
from sqlalchemy import func, select

from app.models.delivered_question import DeliveredQuestion
from scripts.loadtest.clients import Client
from scripts.loadtest.environment import sessions
from scripts.loadtest.scenarios.common import (
    FAN_OUT_LIMIT_SECONDS,
    Classroom,
    Result,
    spread,
)

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
