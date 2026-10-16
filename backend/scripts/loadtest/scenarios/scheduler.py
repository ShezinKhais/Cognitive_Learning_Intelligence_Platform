"""Many sessions on the automatic question cycle.

See common.py for what a scenario returns.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from scripts.loadtest.clients import Client
from scripts.loadtest.environment import Database, Person, Seeded, Server
from scripts.loadtest.scenarios.common import (
    Classroom,
    Result,
)

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
