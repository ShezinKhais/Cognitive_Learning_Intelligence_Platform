"""Run the load and failure-recovery scenarios and write down what happened.

    python -m scripts.loadtest
    python -m scripts.loadtest --students 40 --rounds 8 --database-outage
    python -m scripts.loadtest --only class,reconnect --out results.json

Exit status 0 when every check passed, 1 when any failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.loadtest import environment, scenarios
from scripts.loadtest.environment import BACKEND, Database, Seeded, Server
from scripts.loadtest.report import write_markdown
from scripts.loadtest.scenarios import Classroom, Result

ALL = (
    "class",
    "reconnect",
    "signals",
    "housekeeping",
    "model",
    "crash",
    "restart",
    "database",
    "teams",
    "scheduler",
)

# The class scenarios share one server. Short timings, so a run takes minutes:
# a response window of two seconds, and the watch looking every second.
CLASS_SERVER = {
    "CHECKPOINT_INTERVAL_MIN_SECONDS": "0",
    "CHECKPOINT_INTERVAL_MAX_SECONDS": "0",
    "CHECKPOINT_RESPONSE_WINDOW_SECONDS": "2",
    "SIGNAL_WATCH_SECONDS": "1",
    "ATTENTION_SIGNAL_MIN_INTERVAL_SECONDS": "0.2",
    # A student's signals count at most one every two seconds, so 16
    # seconds of them cover a little under 16.
    "REFOCUS_MIN_SIGNAL_SECONDS": "10",
    # Every few seconds, so a run sees it give way to the class.
    "RETENTION_PURGE_INTERVAL_HOURS": "0.001",
    "ROOM_VOICE_FRESH_SECONDS": "5",
    "ROOM_QUIET_AFTER_SECONDS": "4",
    "ROOM_NEEDS_ATTENTION_AFTER_SECONDS": "7",
}
# The scheduler scenario turns the question cycle on: a question every three
# seconds in every session, one second to answer and two between.
CYCLE_SERVER = {
    "CHECKPOINT_INTERVAL_MIN_SECONDS": "2",
    "CHECKPOINT_INTERVAL_MAX_SECONDS": "2",
    "CHECKPOINT_RESPONSE_WINDOW_SECONDS": "1",
}
CYCLE_SECONDS = 3.0


def machine() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND, capture_output=True, text=True
    ).stdout.strip()
    return {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpus": __import__("os").cpu_count(),
        "python": platform.python_version(),
    }


async def run(args: argparse.Namespace) -> list[Result]:
    chosen = [name for name in ALL if name in args.only]
    if "database" in chosen and not args.database_outage:
        chosen.remove("database")
    results: list[Result] = []
    workdir = Path(tempfile.mkdtemp(prefix="clip-load-"))
    secret = secrets.token_urlsafe(48)
    database: Database = await environment.create_database(args.database_host)
    server = Server(database, secret, workdir, **CLASS_SERVER)
    cycle_server = Server(database, secret, workdir, **CYCLE_SERVER)
    try:
        seeded: Seeded = await environment.seed(
            database, server.settings(), args.students, questions=400
        )
        if any(name != "scheduler" for name in chosen):
            results += await class_scenarios(args, chosen, server, database, seeded)
        if "scheduler" in chosen:
            await server.stop()
            cycle_server.log_path = workdir / "cycle-server.log"
            await cycle_server.start()
            results.append(
                await guarded(
                    "scheduler",
                    scenarios.scheduler_load(
                        cycle_server,
                        database,
                        seeded,
                        seeded.students,
                        classes=args.classes,
                        seconds=args.cycle_seconds,
                        cycle=CYCLE_SECONDS,
                    ),
                )
            )
        for which in (server, cycle_server):
            problems = which.log_problems()
            if problems:
                results.append(server_log_result(which, problems))
    finally:
        await server.kill()
        await cycle_server.kill()
        await environment.drop_database(database)
        print(f"server logs kept in {workdir}", file=sys.stderr)
    return results


def server_log_result(server: Server, problems: list[str]) -> Result:
    result = Result("server-log", f"Errors in {server.log_path.name}")
    result.check("the server logged no error it did not expect", False, f"{len(problems)} line(s)")
    result.notes = problems[:20]
    return result


async def guarded(name: str, scenario: Any) -> Result:
    """Run a scenario, and turn it failing outright into a failed check, so
    one broken scenario does not cost the report the others."""
    began = time.perf_counter()
    try:
        result = await scenario
    except Exception as exc:
        result = Result(name, name)
        result.check("the scenario ran to the end", False, f"{type(exc).__name__}: {exc}"[:400])
    result.figures["scenario_seconds"] = round(time.perf_counter() - began, 1)
    mark = "ok  " if result.passed else "FAIL"
    print(f"[{mark}] {result.title} ({result.figures['scenario_seconds']} s)", file=sys.stderr)
    for check in result.checks:
        if not check.ok:
            print(f"       {check.name}: {check.detail}", file=sys.stderr)
    return result


async def class_scenarios(
    args: argparse.Namespace,
    chosen: list[str],
    server: Server,
    database: Database,
    seeded: Seeded,
) -> list[Result]:
    results: list[Result] = []
    await server.start()
    room = Classroom(server, database, seeded)
    # Every later scenario happens to this class, so it always runs.
    opened = await guarded("class", scenarios.class_under_load(room, seeded.students, args.rounds))
    results.append(opened)
    baseline = opened.figures.get("question_fan_out", {})
    steps = {
        "reconnect": lambda: scenarios.reconnecting(room),
        "signals": lambda: scenarios.signals_and_rooms(room, seconds=16.0, every=0.25),
        "housekeeping": lambda: scenarios.housekeeping_during_class(room, baseline),
        "model": lambda: scenarios.model_down(room),
        "crash": lambda: scenarios.server_crash(room),
        "restart": lambda: scenarios.planned_restart(room),
        "database": lambda: scenarios.database_outage(
            room, args.database_container, args.outage_seconds
        ),
    }
    for name, step in steps.items():
        if name in chosen:
            results.append(await guarded(name, step()))
    await room.end()
    await room.close()
    if "teams" in chosen:
        results.append(
            await guarded("teams", scenarios.teams_meeting(server, seeded, seeded.students))
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--rounds", type=int, default=8, help="questions in the first scenario")
    parser.add_argument(
        "--classes", type=int, default=10, help="sessions in the scheduler scenario"
    )
    parser.add_argument("--cycle-seconds", type=float, default=30.0)
    parser.add_argument("--only", default=",".join(ALL), help="comma-separated scenario names")
    parser.add_argument(
        "--database-outage",
        action="store_true",
        help="also stop and start the Postgres container. It serves the development "
        "database too, so nothing else can use it for those few seconds.",
    )
    parser.add_argument("--database-container", default="clip-postgres")
    parser.add_argument("--database-host", default=None, help="defaults to this machine's name")
    parser.add_argument("--outage-seconds", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=None, help="write the results as JSON")
    parser.add_argument("--markdown", type=Path, default=None, help="write the results as a report")
    args = parser.parse_args(argv)
    args.only = {name.strip() for name in args.only.split(",") if name.strip()}
    unknown = args.only - set(ALL)
    if unknown:
        parser.error(f"unknown scenario(s): {', '.join(sorted(unknown))}")

    results = asyncio.run(run(args))
    document = {
        "machine": machine(),
        "students": args.students,
        "passed": all(result.passed for result in results),
        "scenarios": [result.as_dict() for result in results],
    }
    if args.out:
        args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        write_markdown(args.markdown, document)
    failed = sum(1 for result in results for check in result.checks if not check.ok)
    total = sum(len(result.checks) for result in results)
    print(f"{total - failed} of {total} checks passed", file=sys.stderr)
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
