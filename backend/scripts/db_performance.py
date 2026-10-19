"""Performance queries (Phase 8, BBIS).

    PYTHONPATH=. python scripts/db_performance.py --scale 10

Seeds a larger term on a throwaway database, then runs EXPLAIN ANALYZE on the
queries the platform relies on: the purge, the student export, the audit log, and
the cascades of an erasure and a session purge (both rolled back). Prints a
Markdown section. Never touches the live database.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scripts.db_evidence import prepare, scratch_url
from scripts.db_purge_simulation import seed

BIG_SCAN = 10_000  # a sequential scan over more rows than this is worth a look
EXPIRED = "coalesce(ended_at, end_time, start_time) < now() - interval '120 days'"


def walk(node: dict[str, Any], found: list[dict[str, Any]]) -> None:
    found.append(node)
    for child in node.get("Plans", []):
        walk(child, found)


def describe(root: dict[str, Any]) -> tuple[list[str], list[str]]:
    """How the plan reads its tables, and the big tables it scans whole."""
    nodes: list[dict[str, Any]] = []
    walk(root["Plan"], nodes)
    notes: list[str] = []
    flagged: list[str] = []
    for node in nodes:
        kind = node["Node Type"]
        table = node.get("Relation Name")
        loops = node.get("Actual Loops", 1)
        if kind == "Seq Scan":
            scanned = int(
                (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)) * loops
            )
            notes.append(f"Seq Scan on {table} ({scanned:,} rows)")
            if scanned > BIG_SCAN:
                flagged.append(str(table))
        elif kind in ("Index Scan", "Index Only Scan"):
            notes.append(f"{kind} on {table} using {node.get('Index Name')}")
        elif kind == "Bitmap Index Scan":
            notes.append(f"Bitmap Index Scan using {node.get('Index Name')}")
    return list(dict.fromkeys(notes)), flagged


async def explain(engine: AsyncEngine, sql: str, rolled_back: bool) -> dict[str, Any]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            value = await connection.scalar(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"))
        finally:
            await transaction.rollback()
    data = json.loads(value) if isinstance(value, str) else value
    return data[0]


async def run(name: str, scale: int) -> int:
    engine = create_async_engine(scratch_url(name))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    seeded = await seed(factory, scale)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                'insert into audit_log (log_id, action_type, "timestamp", target_type, details) '
                "select gen_random_uuid(), 'SESSION_STARTED', "
                "now() - (g || ' minutes')::interval, 'session', '{}'::jsonb "
                "from generate_series(1, 50000) g"
            )
        )
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(text("ANALYZE"))
        student = await connection.scalar(text("select student_id from student limit 1"))
        session = await connection.scalar(
            text(f"select session_id from session where status = 'ended' and {EXPIRED} limit 1")
        )
        sizes = {
            row[0]: row[1]
            for row in (
                await connection.execute(
                    text(
                        "select relname, n_live_tup from pg_stat_user_tables "
                        "where relname in ('student_response', 'engagement_record', "
                        "'attention_signal_summary', 'session_participant', 'audit_log') "
                        "order by 1"
                    )
                )
            )
        }

    purge_candidates = (
        f"select session_id from session where {EXPIRED} and status in ('ended', 'cancelled') "
        "order by coalesce(ended_at, end_time, start_time) limit 500"
    )
    queries: list[tuple[str, str, bool]] = [
        ("Purge: the next 500 expired sessions", purge_candidates, False),
        (
            "Purge: archive totals for those sessions",
            "select session_id, student_id, count(*), count(*) filter (where is_correct) "
            f"from student_response where session_id in ({purge_candidates}) group by 1, 2",
            False,
        ),
        (
            "Export: a student's answers with labels",
            "select r.*, c.* from student_response r "
            "left join comprehension_result c on c.response_id = r.response_id "
            f"where r.student_id = '{student}' order by r.submitted_at",
            False,
        ),
        (
            "Export: a student's engagement",
            f"select * from engagement_record where student_id = '{student}' order by timestamp",
            False,
        ),
        (
            "Export: a student's attention summaries",
            "select * from attention_signal_summary "
            f"where student_id = '{student}' order by window_start",
            False,
        ),
        (
            "Export: a student's prompts",
            f"select * from dynamic_prompt where student_id = '{student}'",
            False,
        ),
        (
            "Audit log: newest 50",
            'select * from audit_log order by "timestamp" desc limit 50',
            False,
        ),
        (
            "Audit log: newest 50 of one action",
            "select * from audit_log where action_type = 'SESSION_STARTED' "
            'order by "timestamp" desc limit 50',
            False,
        ),
        (
            "Erase one student (cascade, rolled back)",
            f"delete from student where student_id = '{student}'",
            True,
        ),
        (
            "Purge one session (cascade, rolled back)",
            f"delete from session where session_id = '{session}'",
            True,
        ),
    ]

    lines = ["| Query | Time (ms) | How it reads the data | Verdict |", "|---|---|---|---|"]
    triggers: list[tuple[str, str, float, int]] = []
    flagged_tables: set[str] = set()
    slow = 0
    for label, sql, rolled_back in queries:
        result = await explain(engine, sql, rolled_back)
        notes, flagged = describe(result)
        total = float(result["Execution Time"])
        flagged_tables.update(flagged)
        verdict = "OK"
        if flagged:
            verdict = "WATCH: scans a big table whole"
        if total > 250:
            verdict = "SLOW"
            slow += 1
        lines.append(f"| {label} | {total:,.1f} | {'; '.join(notes) or '-'} | {verdict} |")
        for trigger in result.get("Triggers", []):
            triggers.append(
                (label, trigger["Trigger Name"], float(trigger["Time"]), int(trigger["Calls"]))
            )

    print("## Performance queries\n")
    print(
        f"Seeded {seeded['seeded']:,} rows plus 50,000 audit entries on a throwaway database "
        f"and ran ANALYZE. Table sizes: "
        + ", ".join(f"{table} {int(rows):,}" for table, rows in sizes.items())
        + ".\n"
    )
    print("\n".join(lines))
    print("\n### Cascade triggers that took 1 ms or more\n")
    print("| Query | Constraint | Time (ms) | Calls |\n|---|---|---|---|")
    slow_triggers = [item for item in triggers if item[2] >= 1.0]
    for label, trigger, millis, calls in sorted(slow_triggers, key=lambda item: -item[2]):
        print(f"| {label} | {trigger} | {millis:,.1f} | {calls} |")
    if not slow_triggers:
        print("| - | none | - | - |")
    print(
        "\nBig tables read whole by at least one query: "
        + (", ".join(sorted(flagged_tables)) or "none")
        + "."
    )
    await engine.dispose()
    return 1 if slow else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default="clip_evidence", help="scratch database name")
    parser.add_argument("--scale", type=int, default=10, help="multiplies the number of sessions")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        prepare(args.database)
    return asyncio.run(run(args.database, args.scale))


if __name__ == "__main__":
    raise SystemExit(main())
