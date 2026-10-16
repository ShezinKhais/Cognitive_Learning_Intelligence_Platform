"""A class under load: questions to forty students, reconnecting, attention
signals and breakout rooms, and housekeeping while a class runs.

See common.py for what a scenario returns.
"""

from __future__ import annotations

import asyncio
import time

from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.student_response import StudentResponse
from scripts.loadtest.clients import Client, is_type
from scripts.loadtest.environment import Person
from scripts.loadtest.scenarios.common import (
    CONNECT_LIMIT_SECONDS,
    FAN_OUT_LIMIT_SECONDS,
    RECEIPT_LIMIT_SECONDS,
    RECONNECT_LIMIT_SECONDS,
    Classroom,
    Result,
    spread,
)

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

    # Everyone here has answered every question, so by Cyber 1's rule the
    # camera alone is no grounds for a prompt, however far away they look.
    # Prompting on low signals and low participation is tested in
    # test_classroom_signals.py.
    prompted = {
        index: [e for e in s.of("prompt.attention") if "still with the class" in e.data["message"]]
        for index, s in enumerate(students)
    }
    result.figures["refocus_prompts"] = sum(len(p) for p in prompted.values())
    result.check(
        "nobody who answers every question is prompted on the camera alone",
        not any(prompted.values()),
        {i: len(p) for i, p in prompted.items() if p},
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
