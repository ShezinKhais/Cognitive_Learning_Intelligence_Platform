"""The database, the seeded class and the server process a load run uses."""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.models.consent import Consent
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import ConsentType, Role

BACKEND = Path(__file__).resolve().parents[2]
LOAD_DATABASE = "clip_load"
LOAD_ROLE = "clip_load"
COURSE_CODE = "LOAD101"
STARTUP_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class Person:
    user_id: UUID
    email: str
    role: Role
    token: str = ""


@dataclass
class Seeded:
    course_id: UUID
    lecturer: Person
    admin: Person
    students: list[Person]
    # Staged questions not yet handed to a scenario.
    questions: list[UUID] = field(default_factory=list)


@dataclass(frozen=True)
class Database:
    """The throwaway database, as the server and the harness reach it."""

    url: str  # for the server and SQLAlchemy
    admin_dsn: str  # asyncpg, as the development superuser
    host: str


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def create_database(host: str | None = None) -> Database:
    """Create an empty database and a role of its own, migrated to head.

    The server runs in production mode, which refuses a database on localhost
    and the development password, so the role gets a random one and the host
    is this machine's name. The development superuser from .env creates both.
    """
    dev = urlsplit(get_settings().database_url.replace("+asyncpg", ""))
    admin_dsn = f"postgresql://{dev.username}:{dev.password}@{dev.hostname}:{dev.port or 5432}"
    host = host or socket.gethostname()
    password = secrets.token_urlsafe(24)
    admin = await asyncpg.connect(f"{admin_dsn}/{dev.path.lstrip('/')}")
    try:
        await _drop(admin)
        # Identifiers are constants above, and the password is one this
        # process generated from a URL-safe alphabet.
        await admin.execute(f"CREATE ROLE {LOAD_ROLE} LOGIN PASSWORD '{password}'")
        await admin.execute(f"CREATE DATABASE {LOAD_DATABASE} OWNER {LOAD_ROLE}")
    finally:
        await admin.close()
    inside = await asyncpg.connect(f"{admin_dsn}/{LOAD_DATABASE}")
    try:
        for extension in ("vector", '"uuid-ossp"', "pg_trgm"):
            await inside.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    finally:
        await inside.close()
    url = f"postgresql+asyncpg://{LOAD_ROLE}:{password}@{host}:{dev.port or 5432}/{LOAD_DATABASE}"
    database = Database(url=url, admin_dsn=admin_dsn, host=host)
    await asyncio.to_thread(_migrate, url)
    return database


async def drop_database(database: Database) -> None:
    dev = urlsplit(get_settings().database_url.replace("+asyncpg", ""))
    admin = await asyncpg.connect(f"{database.admin_dsn}/{dev.path.lstrip('/')}")
    try:
        await _drop(admin)
    finally:
        await admin.close()


async def _drop(admin: asyncpg.Connection) -> None:
    await admin.execute(f"DROP DATABASE IF EXISTS {LOAD_DATABASE} WITH (FORCE)")
    await admin.execute(f"DROP ROLE IF EXISTS {LOAD_ROLE}")


def _migrate(url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


def sessions(database: Database) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database.url, poolclass=NullPool)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def seed(database: Database, settings: Settings, students: int, questions: int) -> Seeded:
    """One course, its lecturer, an admin, the students enrolled on it with
    every consent granted, and staged questions for the lecturer to deliver."""

    def person(role: Role, email: str) -> Person:
        user_id = uuid4()
        token, _ = create_access_token(user_id=user_id, role=role, email=email, settings=settings)
        return Person(user_id, email, role, token)

    lecturer = person(Role.LECTURER, "lecturer@load.example.com")
    admin = person(Role.ADMIN, "admin@load.example.com")
    class_ = [person(Role.STUDENT, f"student{n:03d}@load.example.com") for n in range(students)]
    async with sessions(database)() as db:
        course = Course(code=COURSE_CODE, name="Load test course")
        db.add(course)
        await db.flush()
        for who in (lecturer, admin, *class_):
            db.add(
                User(
                    user_id=who.user_id,
                    name=who.email.split("@")[0],
                    role=who.role.value,
                    email=who.email,
                    active=True,
                )
            )
        await db.flush()
        for who in (lecturer, admin):
            db.add(Consent(user_id=who.user_id, consent_type=ConsentType.TERMS.value, granted=True))
        for who in class_:
            db.add(
                Student(
                    user_id=who.user_id,
                    course_id=course.id,
                    consent_status="granted",
                    enrolled_at=date(2026, 9, 1),
                )
            )
            for consent in ConsentType:
                db.add(Consent(user_id=who.user_id, consent_type=consent.value, granted=True))
        material = Material(
            course_id=course.id,
            filename="load.pdf",
            content_type="application/pdf",
            size_bytes=10,
            status="completed",
            uploaded_by_user_id=lecturer.user_id,
        )
        db.add(material)
        await db.flush()
        staged = [
            Question(
                source_material_id=material.id,
                question_text=f"Load question {n}: which option is second?",
                question_type="mcq",
                status="staged",
                options=["First", "Second", "Third", "Fourth"],
                correct_option=1,
                topic=f"Topic {n % 5}",
                source_slide=n + 1,
            )
            for n in range(questions)
        ]
        db.add_all(staged)
        await db.commit()
        return Seeded(
            course_id=course.id,
            lecturer=lecturer,
            admin=admin,
            students=class_,
            questions=[q.question_id for q in staged],
        )


class Server:
    """The backend as a process of its own, so it can be killed and restarted."""

    def __init__(self, database: Database, secret: str, workdir: Path, **env: str) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.ws = f"ws://127.0.0.1:{self.port}/ws/session"
        self.log_path = workdir / "server.log"
        self._workdir = workdir
        self._env = {
            **os.environ,
            "CLIP_ENV": "production",
            "CLIP_SECRET_KEY": secret,
            "DATABASE_URL": database.url,
            "WEB_CONCURRENCY": "1",
            "AI_WARMUP_ENABLED": "false",
            # Nothing listens here, so a model call fails at once and no
            # model is loaded on the machine running the test.
            "OLLAMA_BASE_URL": "http://127.0.0.1:9/v1",
            "UPLOAD_STORAGE_DIR": str(workdir / "uploads"),
            "CLIENT_ID": "",
            "CLIENT_SECRET": "",
            "TENANT_ID": "",
            **env,
        }
        self._process: subprocess.Popen[bytes] | None = None
        self.starts = 0
        # When the test stopped the database, in the log's local time.
        self.outages: list[tuple[datetime, datetime]] = []

    def settings(self) -> Settings:
        """The settings the server process has, for signing tokens it accepts."""
        return Settings(
            _env_file=None,
            **{
                "clip_env": "production",
                "clip_secret_key": self._env["CLIP_SECRET_KEY"],
                "database_url": self._env["DATABASE_URL"],
            },
        )

    async def start(self) -> float:
        """Start the process and wait until it answers. Returns the seconds
        from launch to the first healthy reply."""
        self.starts += 1
        began = time.perf_counter()
        log = self.log_path.open("ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self._process = subprocess.Popen(  # noqa: ASYNC220 - started once, not awaited on
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=BACKEND,
            env=self._env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        log.close()
        async with httpx.AsyncClient(base_url=self.base, timeout=2.0) as http:
            while time.perf_counter() - began < STARTUP_TIMEOUT_SECONDS:
                if self._process.poll() is not None:
                    raise RuntimeError(f"the server exited at startup; see {self.log_path}")
                try:
                    if (await http.get("/api/v1/health")).status_code == 200:
                        return time.perf_counter() - began
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
        raise RuntimeError(f"the server did not start; see {self.log_path}")

    async def stop(self) -> float:
        """Ask the process to shut down as a deploy would, and wait for it.
        Returns how long the shutdown took."""
        process = self._process
        if process is None or process.poll() is not None:
            return 0.0
        began = time.perf_counter()
        if sys.platform == "win32":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.to_thread(process.wait, 30)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait)
        self._process = None
        return time.perf_counter() - began

    async def kill(self) -> None:
        """Stop the process with no warning, as a crash or a host failure would."""
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
            await asyncio.to_thread(self._process.wait)
        self._process = None

    def purge_lines(self) -> list[str]:
        """The line each retention purge run logs, oldest first."""
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [line for line in lines if "retention_purge " in line]

    def log_errors(self) -> tuple[list[str], list[str]]:
        """Every error the server logged, as its first line, split into those
        nothing explains and those a database outage the test caused does.

        An entry is a timestamped line and the lines after it up to the next
        one, so a traceback belongs to the error it follows. One is excused
        only when it was logged inside an outage window and comes from not
        reaching the database; anything else in that window still counts.
        """
        if not self.log_path.exists():
            return [], []
        entries: list[list[str]] = []
        for line in self.log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if _LOGGED_AT.match(line) or not entries:
                entries.append([line])
            else:
                entries[-1].append(line)
        problems, excused = [], []
        for entry in entries:
            head, text = entry[0], "\n".join(entry)
            if " ERROR " not in head and "Traceback" not in text:
                continue
            stamp = _LOGGED_AT.match(head)
            at = datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S,%f") if stamp else None
            during = at is not None and any(start <= at <= end for start, end in self.outages)
            if during and any(marker in text for marker in _DATABASE_UNREACHABLE):
                excused.append(head)
            else:
                problems.append(head)
        return problems, excused

    def log_problems(self) -> list[str]:
        """Errors in the server log that nothing the test did explains."""
        return self.log_errors()[0]


# A log line's timestamp, as logging writes it in local time.
_LOGGED_AT = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) ")
# How not reaching Postgres shows up in a traceback.
_DATABASE_UNREACHABLE = (
    "ConnectionRefusedError",
    "ConnectionResetError",
    "CannotConnectNowError",
    "ConnectionDoesNotExistError",
    "InterfaceError",
)


def now() -> datetime:
    return datetime.now(UTC)
