"""Writing the development accounts to the user table at startup."""

from __future__ import annotations

import asyncio

from app.auth import dev_seed
from app.core.config import get_settings


async def test_seeding_keeps_trying_until_the_database_is_there(monkeypatch):
    """The backend is often started before the database. One failed attempt
    used to be final, and every upload then failed on the missing user."""
    attempts = []

    async def attempt(settings):
        attempts.append(settings)
        return len(attempts) == 3

    monkeypatch.setattr(dev_seed, "_insert_dev_users", attempt)

    await asyncio.wait_for(dev_seed.ensure_dev_users(get_settings(), retry_seconds=0), 1)

    assert len(attempts) == 3


async def test_seeding_never_runs_in_production(monkeypatch):
    attempts = []

    async def attempt(settings):
        attempts.append(settings)
        return True

    monkeypatch.setattr(dev_seed, "_insert_dev_users", attempt)
    production = get_settings().model_copy(update={"clip_env": "production"})

    await dev_seed.ensure_dev_users(production)

    assert production.is_production
    assert attempts == []
