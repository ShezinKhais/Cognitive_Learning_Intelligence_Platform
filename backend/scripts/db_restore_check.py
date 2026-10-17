"""Backup restoration drill (Phase 8, BBIS).

    PYTHONPATH=. python scripts/db_restore_check.py

Seeds a term on a throwaway database (with a separate history database), counts
every table, backs both up, wipes the live copy, restores both into new
databases, and compares every table's row count. Also runs the integrity checks
on the restored copy. Never touches the live database. Prints a Markdown section
and exits 1 if a check failed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.history.database import create_history_tables
from app.services.retention_tasks import SessionDataPurge
from scripts.database_backup import drop, dump, restore
from scripts.db_evidence import integrity, prepare, scratch_url
from scripts.db_purge_simulation import recreate_database, seed


async def table_counts(engine: AsyncEngine) -> dict[str, int]:
    """The exact row count of every table in the public schema."""
    async with engine.connect() as connection:
        names = (
            (
                await connection.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"
                    )
                )
            )
            .scalars()
            .all()
        )
        counts = {}
        for name in names:
            counts[name] = int(await connection.scalar(text(f'select count(*) from "{name}"')))
    return counts


def differences(before: dict[str, int], after: dict[str, int]) -> list[str]:
    return [
        f"{table}: {before.get(table)} -> {after.get(table)}"
        for table in sorted(set(before) | set(after))
        if before.get(table) != after.get(table)
    ]


async def run(name: str) -> int:
    history_name = f"{name}_history"
    restored, restored_history = f"{name}_restored", f"{name}_history_restored"
    live_url, history_url = scratch_url(name), scratch_url(history_name)
    main_engine = create_async_engine(live_url)
    history_engine = create_async_engine(history_url)
    await create_history_tables(history_engine)
    main = async_sessionmaker(main_engine, class_=AsyncSession, expire_on_commit=False)
    history = async_sessionmaker(history_engine, class_=AsyncSession, expire_on_commit=False)

    await seed(main, 1)
    purge = SessionDataPurge(lambda: main, history=lambda: history)
    cutoff = datetime.now(UTC) - timedelta(days=120)
    while await purge.purge(cutoff, 25) == 25:
        pass  # so the history database holds real archived data

    before_main = await table_counts(main_engine)
    before_history = await table_counts(history_engine)

    folder = Path(tempfile.mkdtemp(prefix="clip-restore-drill-"))
    try:
        timings: dict[str, float] = {}

        async def timed(label: str, function, *arguments):  # noqa: ANN001, ANN202
            started = time.perf_counter()
            result = await asyncio.to_thread(function, *arguments)
            timings[label] = time.perf_counter() - started
            return result

        main_dump = await timed("backup main", dump, live_url, folder, "clip")
        history_dump = await timed("backup history", dump, history_url, folder, "clip_history")
        private = all(path.stat().st_mode & 0o777 == 0o600 for path in (main_dump, history_dump))
        size_kb = (main_dump.stat().st_size + history_dump.stat().st_size) // 1024

        # The disaster: every session and student in the live copy, gone.
        async with main_engine.begin() as connection:
            await connection.execute(text('delete from "session"'))
            await connection.execute(text("delete from student"))
        damaged = await table_counts(main_engine)

        for target in (restored, restored_history):
            await asyncio.to_thread(drop, live_url, target)
        await timed("restore main", restore, main_dump, live_url, restored)
        await timed("restore history", restore, history_dump, live_url, restored_history)

        restored_main_engine = create_async_engine(scratch_url(restored))
        restored_history_engine = create_async_engine(scratch_url(restored_history))
        after_main = await table_counts(restored_main_engine)
        after_history = await table_counts(restored_history_engine)
        await restored_main_engine.dispose()
        await restored_history_engine.dispose()

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            integrity_code = await integrity(restored)
        passed_checks = buffer.getvalue().count("| PASS |")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    main_differences = differences(before_main, after_main)
    history_differences = differences(before_history, after_history)
    rows = sum(before_main.values()) + sum(before_history.values())
    checks = [
        ("Backup files are private (mode 600)", private, f"{size_kb} KB in all"),
        (
            "The disaster really removed data from the live copy",
            damaged["student"] == 0 and damaged["session"] == 0 and before_main["student"] > 0,
            f"students {before_main['student']} -> {damaged['student']}, "
            f"sessions {before_main['session']} -> {damaged['session']}",
        ),
        (
            "Every table in the restored main database has its original row count",
            not main_differences and len(after_main) == len(before_main),
            f"{len(before_main)} tables, {sum(before_main.values()):,} rows"
            + ("" if not main_differences else f"; {main_differences[:3]}"),
        ),
        (
            "Every table in the restored history database has its original row count",
            not history_differences and len(after_history) == len(before_history),
            f"{len(before_history)} tables, {sum(before_history.values()):,} rows"
            + ("" if not history_differences else f"; {history_differences[:3]}"),
        ),
        (
            "The restored main database passes the integrity checks",
            integrity_code == 0 and passed_checks == 6,
            f"{passed_checks} of 6 checks",
        ),
    ]

    print("## Backup restoration\n")
    print(
        f"Backed up a seeded term ({rows:,} rows in {len(before_main)} main and "
        f"{len(before_history)} history tables), deleted every session and student from the "
        "live copy, then restored both databases into new ones.\n"
    )
    print("| Step | Seconds |\n|---|---|")
    for label, seconds in timings.items():
        print(f"| {label} | {seconds:.1f} |")
    print("\n| Check | Result | Detail |\n|---|---|---|")
    for check, passed, detail in checks:
        print(f"| {check} | {'PASS' if passed else 'FAIL'} | {detail} |")

    for target in (restored, restored_history):
        await asyncio.to_thread(drop, live_url, target)
    await main_engine.dispose()
    await history_engine.dispose()
    return 0 if all(passed for _, passed, _ in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default="clip_evidence", help="scratch database name")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        prepare(args.database)
        recreate_database(f"{args.database}_history")
    return asyncio.run(run(args.database))


if __name__ == "__main__":
    raise SystemExit(main())
