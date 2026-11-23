"""Development accounts as rows in the user table.

Sign-in in development checks the in-memory accounts in app.auth.store, but
data a user creates points at the user table: source_material.uploaded_by_user_id
is a foreign key to it. Without these rows the first upload by a development
lecturer failed on that key. Never runs in production, where accounts are real.

The development student is also enrolled on a development course, since a
student can only join a live session for a course they are enrolled on.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.store import dev_user_records
from app.core.config import Settings
from app.models.course import Course
from app.models.student import Student
from app.models.user import User
from app.schemas.identity import Role

log = logging.getLogger("clip.auth")

# An unreachable database should fail an attempt fast rather than after the
# driver's default minute.
CONNECT_TIMEOUT_SECONDS = 3
# Between attempts while the database is not there yet.
RETRY_SECONDS = 5.0

# The course the development student is enrolled on. A development lecturer's
# sessions are created for it.
DEV_COURSE_CODE = "CLIP101"
DEV_COURSE_NAME = "C.L.I.P development course"


async def ensure_dev_users(settings: Settings, retry_seconds: float = RETRY_SECONDS) -> None:
    """Insert any development account the user table does not have yet.

    Runs in the background from startup and keeps trying until it succeeds or
    the app shuts down. The backend is often started before the database, and
    a single attempt left every upload failing on the missing user until the
    next restart. A database that cannot be reached is logged once, not
    raised: authentication does not need it, and the tests that run without
    one should still start the app.
    """
    if settings.is_production:
        return

    warned = False
    while not await _insert_dev_users(settings):
        if not warned:
            log.warning(
                "development accounts could not be written to the user table yet; "
                "uploads by them will fail until the database is reachable. Retrying."
            )
            warned = True
        await asyncio.sleep(retry_seconds)
    if warned:
        log.info("development accounts written to the user table")


async def _insert_dev_users(settings: Settings) -> bool:
    """One attempt. Uses a short-lived engine of its own so nothing it opens is
    bound to the startup event loop."""
    rows = [
        {
            "user_id": record.id,
            "name": record.full_name,
            "role": record.role.value,
            "email": record.email,
            "password_hash": record.password_hash,
            "active": record.active,
        }
        for record in dev_user_records()
    ]
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"timeout": CONNECT_TIMEOUT_SECONDS},
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(insert(User).values(rows).on_conflict_do_nothing())
            await connection.execute(
                insert(Course)
                .values(code=DEV_COURSE_CODE, name=DEV_COURSE_NAME)
                .on_conflict_do_nothing(index_elements=[Course.code])
            )
            course_id = (
                await connection.execute(select(Course.id).where(Course.code == DEV_COURSE_CODE))
            ).scalar_one()
            students = [record.id for record in dev_user_records() if record.role is Role.STUDENT]
            if students:
                await connection.execute(
                    insert(Student)
                    .values(
                        [
                            {
                                "user_id": user_id,
                                "course_id": course_id,
                                "consent_status": "granted",
                                "enrolled_at": datetime.now(UTC).date(),
                            }
                            for user_id in students
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=[Student.user_id])
                )
    except Exception as exc:
        log.debug("development account insert failed: %s", type(exc).__name__)
        return False
    finally:
        await engine.dispose()
    return True
