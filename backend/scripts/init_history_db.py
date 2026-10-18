"""Create the history tables in the database HISTORY_DATABASE_URL points at.

    PYTHONPATH=. python scripts/init_history_db.py

Create the (empty) database first, for example: createdb clip_history.
Safe to run again.
"""

from __future__ import annotations

import asyncio

from app.history.database import create_history_tables, history_enabled


async def main() -> None:
    if not history_enabled():
        raise SystemExit("HISTORY_DATABASE_URL is not set, so there is nothing to create.")
    await create_history_tables()
    print("History tables are ready.")


if __name__ == "__main__":
    asyncio.run(main())
