"""Back up and restore the databases.

    python scripts/database_backup.py backup --out backups --keep 30
    python scripts/database_backup.py restore backups/clip-20261017T020000Z.dump --into clip_restore

`backup` writes a dump of the main database, and of the history database when
HISTORY_DATABASE_URL is set, then keeps only the newest --keep of each. Dumps
hold personal data: they are created readable by their owner only, and
`backups/` is git-ignored.

`restore` loads a dump into a database you name, creating it when missing. It
refuses the live database unless --replace-live is given. See
docs/backup-restore.md, including what a restore undoes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings


class CreateFailed(RuntimeError):
    """The scratch database could not be created."""


class RestoreFailed(RuntimeError):
    """pg_restore reported an error that is not a known harmless one."""


# A pg_dump newer than the server writes settings the server does not have.
# pg_restore reports each as an error, and the rest of the restore still runs.
HARMLESS = ('unrecognized configuration parameter "transaction_timeout"',)


def unexpected_errors(stderr: str) -> list[str]:
    """The errors in pg_restore's output that are not known to be harmless."""
    errors = [line for line in stderr.splitlines() if line.startswith("pg_restore: error:")]
    return [line for line in errors if not any(text in line for text in HARMLESS)]


def plain_url(url_text: str) -> URL:
    return make_url(url_text).set(drivername="postgresql")


def environment(url: URL) -> dict[str, str]:
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def connection_args(url: URL) -> list[str]:
    args: list[str] = []
    if url.host:
        args += ["--host", url.host]
    if url.port:
        args += ["--port", str(url.port)]
    if url.username:
        args += ["--username", url.username]
    return args


def dump(url_text: str, out_dir: Path, prefix: str, now: datetime | None = None) -> Path:
    url = plain_url(url_text)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{prefix}-{stamp}.dump"
    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            *connection_args(url),
            "--file",
            str(path),
            url.database,
        ],
        env=environment(url),
        check=True,
    )
    path.chmod(0o600)
    return path


def prune(out_dir: Path, prefix: str, keep: int) -> list[Path]:
    """Delete all but the newest `keep` dumps with this prefix. Returns the deleted."""
    if keep < 1:
        raise ValueError("Keep at least one backup")
    files = sorted(out_dir.glob(f"{prefix}-*.dump"))
    old = files[:-keep]
    for path in old:
        path.unlink()
    return old


def restore(dump_file: Path, url_text: str, target: str) -> None:
    """Load a dump into the database `target` on the same server, creating it
    when it does not exist."""
    url = plain_url(url_text)
    created = subprocess.run(
        ["createdb", *connection_args(url), target],
        env=environment(url),
        capture_output=True,
        text=True,
    )
    if created.returncode != 0 and "already exists" not in created.stderr:
        raise CreateFailed(created.stderr.strip())
    result = subprocess.run(
        [
            "pg_restore",
            "--no-owner",
            "--clean",
            "--if-exists",
            *connection_args(url),
            "--dbname",
            target,
            str(dump_file),
        ],
        env=environment(url),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        failures = unexpected_errors(result.stderr)
        if failures or "pg_restore: error:" not in result.stderr:
            raise RestoreFailed(result.stderr.strip())


def drop(url_text: str, target: str) -> None:
    url = plain_url(url_text)
    subprocess.run(
        ["dropdb", "--if-exists", *connection_args(url), target],
        env=environment(url),
        check=True,
    )


def run_backup(args: argparse.Namespace) -> int:
    settings = get_settings()
    out = Path(args.out)
    jobs = [("clip", settings.database_url)]
    if settings.history_database_url:
        jobs.append(("clip_history", settings.history_database_url))
    for prefix, url in jobs:
        path = dump(url, out, prefix)
        removed = prune(out, prefix, args.keep)
        print(f"wrote {path} (removed {len(removed)} old)")
    return 0


def run_restore(args: argparse.Namespace) -> int:
    settings = get_settings()
    live = {plain_url(settings.database_url).database}
    if settings.history_database_url:
        live.add(plain_url(settings.history_database_url).database)
    if args.into in live and not args.replace_live:
        raise SystemExit(
            f"{args.into} is a live database. Restore into another name, or pass --replace-live."
        )
    restore(Path(args.file), settings.database_url, args.into)
    print(f"restored {args.file} into {args.into}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="dump the databases")
    backup.add_argument("--out", default="backups")
    backup.add_argument("--keep", type=int, default=30)
    backup.set_defaults(run=run_backup)
    again = commands.add_parser("restore", help="load a dump into a named database")
    again.add_argument("file")
    again.add_argument("--into", required=True)
    again.add_argument("--replace-live", action="store_true")
    again.set_defaults(run=run_restore)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
