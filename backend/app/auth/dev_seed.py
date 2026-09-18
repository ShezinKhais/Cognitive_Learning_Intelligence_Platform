"""Development accounts as rows in the user table.

Sign-in in development checks the in-memory accounts in app.auth.store, but
data a user creates points at the user table: source_material.uploaded_by_user_id
is a foreign key to it. Without these rows the first upload by a development
lecturer failed on that key. Never runs in production, where accounts are real.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.store import dev_user_records
from app.core.config import Settings
from app.models.user import User

log = logging.getLogger("clip.auth")

# Startup waits on this, so an unreachable database must fail fast rather than
# after the driver's default minute.
CONNECT_TIMEOUT_SECONDS = 3


async def ensure_dev_users(settings: Settings) -> None:
    """Insert any development account the user table does not have yet.

    Uses a short-lived engine of its own so nothing it opens is bound to the
    startup event loop. A database that cannot be reached is logged, not
    raised: authentication does not need it, and the tests that run without
    one should still start the app.
    """
    if settings.is_production:
        return

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
    except Exception as exc:
        log.warning(
            "development accounts could not be written to the user table (%s); "
            "uploads by them will fail until the database is reachable",
            type(exc).__name__,
        )
    finally:
        await engine.dispose()
