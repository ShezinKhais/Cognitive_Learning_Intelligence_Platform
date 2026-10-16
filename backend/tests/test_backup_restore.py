"""Backups: a dump is private, old ones are pruned, and a dump of the real
database restores into a scratch one. The restore test needs the PostgreSQL
client tools and a database user that may create databases, and skips without."""

from __future__ import annotations

import shutil
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from scripts.database_backup import (
    CreateFailed,
    drop,
    dump,
    prune,
    restore,
    unexpected_errors,
)

from .database_support import require_database

TOOLS = ("pg_dump", "pg_restore", "createdb", "dropdb")
needs_postgres_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in TOOLS),
    reason="the PostgreSQL client tools are not installed",
)


def test_only_the_newest_backups_are_kept(tmp_path):
    for day in range(1, 5):
        (tmp_path / f"clip-2001010{day}T000000Z.dump").write_bytes(b"x")
    (tmp_path / "clip_history-20010101T000000Z.dump").write_bytes(b"x")

    removed = prune(tmp_path, "clip", keep=2)

    assert [path.name for path in removed] == [
        "clip-20010101T000000Z.dump",
        "clip-20010102T000000Z.dump",
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "clip-20010103T000000Z.dump",
        "clip-20010104T000000Z.dump",
        "clip_history-20010101T000000Z.dump",
    ]


def test_at_least_one_backup_must_be_kept(tmp_path):
    with pytest.raises(ValueError):
        prune(tmp_path, "clip", keep=0)


async def version_of(url_text: str, database: str | None = None) -> str:
    url = make_url(url_text)
    if database:
        url = url.set(database=database)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("select version_num from alembic_version"))
    finally:
        await engine.dispose()


@needs_postgres_tools
async def test_a_backup_restores_into_a_scratch_database(tmp_path):
    require_database()
    url = get_settings().database_url
    scratch = f"clip_restore_{uuid.uuid4().hex[:8]}"

    path = dump(url, tmp_path, "clip")

    assert path.stat().st_size > 0
    assert path.stat().st_mode & 0o077 == 0
    try:
        try:
            restore(path, url, scratch)
        except CreateFailed as error:
            pytest.skip(f"this database user may not create databases: {error}")
        assert await version_of(url, scratch) == await version_of(url)
    finally:
        drop(url, scratch)


def test_a_newer_dump_tool_setting_is_not_treated_as_a_failure():
    stderr = (
        "pg_restore: error: could not execute query: ERROR:  unrecognized configuration "
        'parameter "transaction_timeout"\n'
        "Command was: SET transaction_timeout = 0;\n"
        "pg_restore: warning: errors ignored on restore: 1\n"
    )

    assert unexpected_errors(stderr) == []


def test_any_other_restore_error_is_a_failure():
    stderr = (
        'pg_restore: error: could not execute query: ERROR:  relation "audit_log" already exists\n'
        "pg_restore: warning: errors ignored on restore: 1\n"
    )

    assert len(unexpected_errors(stderr)) == 1
