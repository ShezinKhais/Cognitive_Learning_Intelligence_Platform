"""Purge simulation (Phase 8, BBIS).

    PYTHONPATH=. python scripts/db_purge_simulation.py --scale 5

Seeds a term on a throwaway database (default clip_evidence, plus a separate
clip_evidence_history for the history side), runs the real purge runner against
it in small batches, interrupts it once the way a starting class would, resumes
it, then checks what is left. Prints a Markdown section and exits 1 if a check
failed. Never touches the live database.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.history.database import create_history_tables
from app.history.models import ArchivedSession, StudentSemesterSummary
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.comprehension_result import ComprehensionResult
from app.models.course import Course
from app.models.engagement_record import EngagementRecord
from app.models.material import Material
from app.models.question import Question
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.services.purge_runner import PurgeRunner
from app.services.retention import purge_expired
from app.services.retention_tasks import RosterSyncPurge, SessionDataPurge, TeamsMappingPurge
from scripts.database_backup import connection_args, environment, plain_url
from scripts.db_evidence import prepare, scratch_url

STUDENTS = 30
QUESTIONS = 6


class Timed:
    """Wraps a purge task and records how long each batch took."""

    def __init__(self, task: Any, log: list[tuple[str, int, float]]) -> None:
        self.task = task
        self.name = task.name
        self.log = log

    async def purge(self, cutoff: datetime, limit: int) -> int:
        started = time.perf_counter()
        removed = await self.task.purge(cutoff, limit)
        self.log.append((self.name, removed, time.perf_counter() - started))
        return removed


def recreate_database(name: str) -> None:
    live = plain_url(get_settings().database_url)
    if name == live.database:
        raise SystemExit(f"{name} is the live database. Pick another name.")
    env = environment(live)
    args = connection_args(live)
    subprocess.run(["dropdb", "--if-exists", *args, name], env=env, check=True)
    subprocess.run(["createdb", *args, name], env=env, check=True)


async def seed(factory: async_sessionmaker[AsyncSession], scale: int) -> dict[str, Any]:
    """Seed a term. Returns what was seeded, so the checks know what to expect."""
    now = datetime.now(UTC)
    async with factory() as db:
        lecturer = User(name="Sim Lecturer", role="lecturer", email=f"l-{uuid4().hex}@sim.test")
        course = Course(code=f"SIM-{uuid4().hex[:8]}", name="Simulation")
        db.add_all([lecturer, course])
        await db.flush()
        users = [
            User(name=f"Sim Student {i}", role="student", email=f"s{i}-{uuid4().hex}@sim.test")
            for i in range(STUDENTS)
        ]
        db.add_all(users)
        await db.flush()
        students = [
            Student(
                user_id=user.user_id,
                course_id=course.id,
                consent_status="granted",
                enrolled_at=now.date(),
            )
            for user in users
        ]
        material = Material(
            course_id=course.id,
            uploaded_by_user_id=lecturer.user_id,
            filename="sim.pdf",
            content_type="application/pdf",
            size_bytes=1,
            status="completed",
        )
        db.add_all([*students, material])
        await db.flush()
        lecturer_id, course_id, material_id = lecturer.user_id, course.id, material.id
        student_ids = [student.student_id for student in students]
        await db.commit()

    groups = [("expired", 125 + i % 300, "ended") for i in range(60 * scale)]
    groups += [("kept", 1 + i % 110, "ended") for i in range(40 * scale)]
    groups += [
        ("live", 200 + i, status)
        for i, status in enumerate(("active", "prepared", "ending", "active", "prepared"))
    ]
    rows: dict[str, list[dict[str, Any]]] = {
        key: []
        for key in ("sessions", "questions", "people", "answers", "labels", "engage", "watch")
    }
    tally = {kind: Counter() for kind in ("expired", "kept", "live")}
    attempted: Counter = Counter()
    right_by: Counter = Counter()
    for index, (kind, age, status) in enumerate(groups):
        session_id = uuid4()
        ended = now - timedelta(days=age)
        rows["sessions"].append(
            {
                "session_id": session_id,
                "instructor_id": lecturer_id,
                "course_id": course_id,
                "start_time": ended - timedelta(hours=1),
                "end_time": ended,
                "ended_at": ended if status == "ended" else None,
                "mode": "live",
                "status": status,
            }
        )
        tally[kind]["sessions"] += 1
        question_ids = []
        for _ in range(QUESTIONS):
            question_id = uuid4()
            question_ids.append(question_id)
            rows["questions"].append(
                {
                    "question_id": question_id,
                    "source_material_id": material_id,
                    "session_id": session_id,
                    "question_text": "Which option is correct?",
                    "question_type": "mcq",
                    "status": "delivered",
                    "difficulty": "easy",
                    "topic": "Simulation",
                    "options": ["No", "Yes"],
                    "correct_option": 1,
                }
            )
        tally[kind]["questions"] += QUESTIONS
        for i, student_id in enumerate(student_ids):
            if (i + index) % 4 == 0:
                continue  # this student was not there
            rows["people"].append(
                {"participant_id": uuid4(), "session_id": session_id, "student_id": student_id}
            )
            tally[kind]["participants"] += 1
            for q, question_id in enumerate(question_ids):
                right = (i + index + q) % 3 != 0
                response_id = uuid4()
                rows["answers"].append(
                    {
                        "response_id": response_id,
                        "session_id": session_id,
                        "student_id": student_id,
                        "question_id": question_id,
                        "selected_option": 1 if right else 0,
                        "is_correct": right,
                    }
                )
                rows["labels"].append(
                    {
                        "result_id": uuid4(),
                        "response_id": response_id,
                        "label": "mastered" if right else "struggling",
                        "confidence_score": 0.9,
                        "score": 1.0 if right else 0.0,
                        "ai_feedback_text": "Simulated.",
                    }
                )
                tally[kind]["answers"] += 1
                tally[kind]["labels"] += 1
                if kind == "expired":
                    attempted[student_id] += 1
                    right_by[student_id] += int(right)
            for _ in range(3):
                rows["engage"].append(
                    {
                        "record_id": uuid4(),
                        "session_id": session_id,
                        "student_id": student_id,
                        "attempt_rate": 1.0,
                        "attention_signal": "present",
                        "engagement_score": 0.5,
                    }
                )
            for k in range(5):
                rows["watch"].append(
                    {
                        "summary_id": uuid4(),
                        "session_id": session_id,
                        "student_id": student_id,
                        "window_start": ended + timedelta(minutes=k),
                        "window_seconds": 60.0,
                        "sample_count": 12,
                        "gaze_on_screen_ratio": 0.5,
                        "face_present_ratio": 1.0,
                        "speaking_ratio": 0.0,
                    }
                )
            tally[kind]["engagement"] += 3
            tally[kind]["attention"] += 5

    for key, model in (
        ("sessions", Session),
        ("questions", Question),
        ("people", SessionParticipant),
        ("answers", StudentResponse),
        ("labels", ComprehensionResult),
        ("engage", EngagementRecord),
        ("watch", AttentionSignalSummary),
    ):
        for start in range(0, len(rows[key]), 5000):
            async with factory() as db:
                await db.execute(insert(model), rows[key][start : start + 5000])
                await db.commit()
    return {
        "tally": tally,
        "seeded": sum(len(value) for value in rows.values()),
        "attempted": sum(attempted.values()),
        "right": sum(right_by.values()),
    }


async def simulate(name: str, scale: int, batch: int) -> int:
    history_name = f"{name}_history"
    main_engine = create_async_engine(scratch_url(name))
    history_engine = create_async_engine(scratch_url(history_name))
    await create_history_tables(history_engine)
    main_factory = async_sessionmaker(main_engine, class_=AsyncSession, expire_on_commit=False)
    history_factory = async_sessionmaker(
        history_engine, class_=AsyncSession, expire_on_commit=False
    )

    seeded = await seed(main_factory, scale)
    tally = seeded["tally"]
    gone, kept, live = tally["expired"], tally["kept"], tally["live"]
    log: list[tuple[str, int, float]] = []

    def make_runner(busy: Callable[[], bool]) -> PurgeRunner:
        runner = PurgeRunner(
            retention=lambda: timedelta(days=120), busy=busy, batch_size=batch, pause=0.0
        )
        for task in (
            SessionDataPurge(lambda: main_factory, history=lambda: history_factory),
            RosterSyncPurge(lambda: main_factory),
            TeamsMappingPurge(lambda: main_factory),
        ):
            runner.register(Timed(task, log))
        return runner

    async with main_factory() as db:
        preview = await purge_expired(db, dry_run=True, retention_days=120)

    checks_made = {"n": 0}

    def a_class_starts() -> bool:
        checks_made["n"] += 1
        return checks_made["n"] > 3

    started = time.perf_counter()
    partial = await make_runner(a_class_starts).run()
    final = await make_runner(lambda: False).run()
    elapsed = time.perf_counter() - started

    async def history_totals() -> tuple[tuple[int, ...], int]:
        columns = (
            "sessions_attended",
            "questions_attempted",
            "questions_correct",
            "engagement_count",
            "gaze_count",
        )
        async with history_factory() as history_db:
            row = (
                await history_db.execute(
                    select(
                        *(
                            func.coalesce(func.sum(getattr(StudentSemesterSummary, column)), 0)
                            for column in columns
                        )
                    )
                )
            ).one()
            markers = await history_db.scalar(select(func.count()).select_from(ArchivedSession))
        return tuple(int(value) for value in row), int(markers or 0)

    before_again = await history_totals()
    again = await make_runner(lambda: False).run()
    after_again = await history_totals()

    counted: dict[str, int] = {}
    async with main_factory() as db:
        for label, model in (
            ("sessions", Session),
            ("questions", Question),
            ("participants", SessionParticipant),
            ("answers", StudentResponse),
            ("labels", ComprehensionResult),
            ("engagement", EngagementRecord),
            ("attention", AttentionSignalSummary),
        ):
            counted[label] = await db.scalar(select(func.count()).select_from(model)) or 0
        unlinked = await db.scalar(
            select(func.count()).select_from(Question).where(Question.session_id.is_(None))
        )
        live_left = await db.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.status.in_(("active", "prepared", "ending")))
        )
        audited = await db.scalar(
            text(
                "select coalesce(sum((details->>'sessions')::int), 0) from audit_log "
                "where action_type = 'RETENTION_PURGE' and details->>'task' = 'session-data'"
            )
        )

    expected_after = {
        label: kept[label] + live[label]
        for label in ("sessions", "participants", "answers", "labels", "engagement", "attention")
    }
    expected_after["questions"] = gone["questions"] + kept["questions"] + live["questions"]
    totals, markers = after_again
    expected_history = (
        gone["participants"],
        seeded["attempted"],
        seeded["right"],
        gone["engagement"],
        gone["attention"],
    )
    removed_rows = sum(
        gone[label]
        for label in ("sessions", "participants", "answers", "labels", "engagement", "attention")
    )
    session_batches = [seconds for task, n, seconds in log if task == "session-data" and n > 0]
    deleted_total = partial.deleted.get("session-data", 0) + final.deleted.get("session-data", 0)

    checks = [
        (
            "Preview counts match what was seeded",
            (preview.sessions, preview.answers) == (gone["sessions"], gone["answers"]),
            f"{preview.sessions} sessions, {preview.answers} answers",
        ),
        (
            "The purge gave way when a class started, then resumed",
            partial.gave_way and not final.gave_way,
            f"first run deleted {partial.deleted.get('session-data', 0)}, second finished",
        ),
        (
            "Every expired session was deleted, once",
            deleted_total == gone["sessions"],
            f"{deleted_total} of {gone['sessions']}",
        ),
        (
            "Current and live sessions and everything under them are untouched",
            all(counted[key] == expected_after[key] for key in expected_after),
            ", ".join(f"{key} {counted[key]}" for key in expected_after),
        ),
        (
            "No active, prepared or ending session was purged",
            live_left == live["sessions"],
            f"{live_left} left",
        ),
        (
            "Questions stay, with their session link cleared",
            unlinked == gone["questions"],
            f"{unlinked} unlinked",
        ),
        (
            "The audit log adds up to what was deleted",
            int(audited or 0) == gone["sessions"],
            f"{audited} sessions audited",
        ),
        (
            "History holds exactly the archived totals",
            totals == expected_history and markers == gone["sessions"],
            f"{totals}, {markers} sessions marked",
        ),
        (
            "A second run deletes nothing and counts nothing twice",
            sum(again.deleted.values()) == 0 and before_again == after_again,
            f"deleted {sum(again.deleted.values())}",
        ),
    ]

    print("## Purge simulation\n")
    print(
        f"Seeded {seeded['seeded']:,} rows on a throwaway database: {STUDENTS} students, "
        f"{gone['sessions']} sessions past retention, {kept['sessions']} current, "
        f"{live['sessions']} live-status with old dates. Batch size {batch}.\n"
    )
    print(
        f"Purged {removed_rows:,} rows in {elapsed:.1f} s ({removed_rows / elapsed:,.0f} rows/s), "
        f"{len(session_batches)} session batches, slowest {max(session_batches, default=0):.2f} s, "
        f"average {sum(session_batches) / max(len(session_batches), 1):.2f} s.\n"
    )
    print("| Check | Result | Detail |")
    print("|---|---|---|")
    for check, passed, detail in checks:
        print(f"| {check} | {'PASS' if passed else 'FAIL'} | {detail} |")
    await main_engine.dispose()
    await history_engine.dispose()
    return 0 if all(passed for _, passed, _ in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default="clip_evidence", help="scratch database name")
    parser.add_argument("--scale", type=int, default=1, help="multiplies the number of sessions")
    parser.add_argument("--batch", type=int, default=25, help="sessions per purge batch")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        prepare(args.database)
        recreate_database(f"{args.database}_history")
    return asyncio.run(simulate(args.database, args.scale, args.batch))


if __name__ == "__main__":
    raise SystemExit(main())
