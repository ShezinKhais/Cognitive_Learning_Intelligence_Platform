"""Database integrity and recovery evidence (Phase 8, BBIS).

    PYTHONPATH=. python scripts/db_evidence.py prepare
    PYTHONPATH=. python scripts/db_evidence.py integrity

Everything runs on a throwaway database (default: clip_evidence) created next to
the live one, never on the live data. `prepare` drops and recreates it, then
applies every migration. Each command prints a Markdown section for
docs/database-integrity-and-recovery.md and exits 1 if a check failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import Base
from scripts.database_backup import connection_args, environment, plain_url

SCRATCH = "clip_evidence"
BACKEND = Path(__file__).resolve().parents[1]

FOREIGN_KEYS = text(
    """
    SELECT c.conrelid::regclass::text AS table_name,
           a.attname AS column_name,
           c.confrelid::regclass::text AS references_table,
           CASE c.confdeltype
               WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
               WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT'
           END AS on_delete
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.contype = 'f' AND c.confrelid::regclass::text IN ('session', 'student')
    ORDER BY 3, 1, 2
    """
)


def require_scratch_name(name: str) -> None:
    """Refuse any database that is not clearly a throwaway one.

    The scripts drop and recreate what they are pointed at, so a typo in
    --database must never reach a real database."""
    if "evidence" not in name:
        raise SystemExit(f"{name} is not a scratch database: its name must contain 'evidence'.")


def scratch_url(name: str) -> str:
    require_scratch_name(name)
    live = get_settings().database_url
    return make_url(live).set(database=name).render_as_string(hide_password=False)


async def create_extension(name: str, extension: str) -> None:
    engine = create_async_engine(
        scratch_url(name), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    async with engine.connect() as connection:
        await connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
    await engine.dispose()


def prepare(name: str) -> None:
    require_scratch_name(name)
    live = plain_url(get_settings().database_url)
    if name == live.database:
        raise SystemExit(f"{name} is the live database. Pick another name.")
    env = environment(live)
    args = connection_args(live)
    subprocess.run(["dropdb", "--if-exists", *args, name], env=env, check=True)
    subprocess.run(["createdb", *args, name], env=env, check=True)
    asyncio.run(create_extension(name, "vector"))
    migrate_env = dict(os.environ, DATABASE_URL=scratch_url(name))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=migrate_env,
        cwd=BACKEND,
        check=True,
    )
    print(f"Scratch database {name} is ready, at the latest migration.")


def schema_diff(connection) -> list:  # noqa: ANN001
    import app.models  # noqa: F401  (registers every table)

    return compare_metadata(MigrationContext.configure(connection), Base.metadata)


async def integrity(name: str) -> int:
    engine = create_async_engine(scratch_url(name), poolclass=NullPool)
    results: list[tuple[str, bool, str]] = []
    async with engine.connect() as connection:
        heads = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()
        results.append(("One migration head", len(heads) == 1, ", ".join(heads)))

        current = await connection.scalar(text("select version_num from alembic_version"))
        results.append(("Database is at the head", [current] == heads, str(current)))

        diff = await connection.run_sync(schema_diff)
        results.append(
            (
                "Schema matches the models",
                not diff,
                "no differences" if not diff else f"{len(diff)}: {str(diff[:3])[:300]}",
            )
        )

        unvalidated = (
            (
                await connection.execute(
                    text(
                        "select conrelid::regclass::text || '.' || conname from pg_constraint "
                        "where not convalidated"
                    )
                )
            )
            .scalars()
            .all()
        )
        results.append(("Every constraint is validated", not unvalidated, ", ".join(unvalidated)))

        broken = (
            (
                await connection.execute(
                    text("select indexrelid::regclass::text from pg_index where not indisvalid")
                )
            )
            .scalars()
            .all()
        )
        results.append(("Every index is valid", not broken, ", ".join(broken)))

        rules = (await connection.execute(FOREIGN_KEYS)).all()
        blocking = [
            f"{row.table_name}.{row.column_name} -> {row.references_table}"
            for row in rules
            if row.on_delete in ("NO ACTION", "RESTRICT")
        ]
        results.append(
            (
                "No foreign key blocks deleting a session or a student",
                not blocking,
                ", ".join(blocking) or f"{len(rules)} keys checked",
            )
        )
    await engine.dispose()

    print("## Integrity\n")
    print("| Check | Result | Detail |\n|---|---|---|")
    for check, passed, detail in results:
        print(f"| {check} | {'PASS' if passed else 'FAIL'} | {detail or '-'} |")
    print("\n### Delete rules on keys that point at `session` and `student`\n")
    print("| Table | Column | Points at | On delete |\n|---|---|---|---|")
    for row in rules:
        cells = (row.table_name, row.column_name, row.references_table, row.on_delete)
        print("| " + " | ".join(cells) + " |")
    return 0 if all(passed for _, passed, _ in results) else 1


def alembic(name: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=scratch_url(name))
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env=env,
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )


async def current_revision(name: str) -> str | None:
    engine = create_async_engine(scratch_url(name), poolclass=NullPool)
    async with engine.connect() as connection:
        value = await connection.scalar(text("select version_num from alembic_version"))
    await engine.dispose()
    return value


def rollback(name: str) -> int:
    require_scratch_name(name)
    if name == plain_url(get_settings().database_url).database:
        raise SystemExit(f"{name} is the live database. Pick another name.")
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    revisions = list(script.walk_revisions())  # the head first
    rows: list[tuple[str, str, str, bool, float, str]] = []

    def step(direction: str, revision, command: tuple[str, ...], expected) -> bool:  # noqa: ANN001
        started = time.perf_counter()
        result = alembic(name, *command)
        reached = asyncio.run(current_revision(name))
        passed = result.returncode == 0 and reached == expected
        note = "" if passed else (result.stderr or "")[-300:].replace("\n", " ")
        description = (revision.doc or "").splitlines()[0].replace("|", "/")
        rows.append(
            (direction, revision.revision, description, passed, time.perf_counter() - started, note)
        )
        print(".", end="", file=sys.stderr, flush=True)
        return passed

    ok = True
    for revision in revisions:
        if not step("down", revision, ("downgrade", "-1"), revision.down_revision):
            ok = False
            break
    if ok:
        for revision in reversed(revisions):
            if not step("up", revision, ("upgrade", "+1"), revision.revision):
                ok = False
                break
    print(file=sys.stderr)

    down = [row for row in rows if row[0] == "down"]
    up = [row for row in rows if row[0] == "up"]
    print("## Migration rollback\n")
    print(
        f"Every migration was downgraded one step at a time from the head to the empty "
        f"database ({len(down)} of {len(revisions)} steps), then upgraded one step at a time "
        f"back to the head ({len(up)} of {len(revisions)} steps).\n"
    )
    print(f"**Result: {'PASS' if ok else 'FAIL'}**\n")
    print("| Direction | Migration | Description | Result | Seconds | Note |")
    print("|---|---|---|---|---|---|")
    for direction, revision_id, description, passed, seconds, note in rows:
        result = "PASS" if passed else "FAIL"
        print(
            f"| {direction} | {revision_id} | {description} | {result} | {seconds:.1f} | {note} |"
        )
    if not ok:
        return 1
    print("\nAfter the full cycle:\n")
    return asyncio.run(integrity(name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default=SCRATCH, help="scratch database name")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="recreate the scratch database at the latest migration")
    commands.add_parser("integrity", help="structural integrity checks")
    commands.add_parser("rollback", help="walk every migration down and up again")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.database)
        return 0
    if args.command == "rollback":
        return rollback(args.database)
    return asyncio.run(integrity(args.database))


if __name__ == "__main__":
    raise SystemExit(main())
