"""Print what a deployed backend is running, as JSON, for the release record.

Run inside the backend container, from the repository root:

    docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env \
        exec -T backend python - < backend/scripts/record_release.py

It answers the questions a release record has to (#255): which commit, which
database migration against the code's head, which switches are on, which
models and prompt versions answer students, and which Python packages are
installed. Image ids are read on the host; the docs say how.

Only safe values are printed: the commit, version strings, true/false
switches, model names and digests, and a hash of the package list. No URL,
key, secret, tenant or account id is read into the output, so the JSON can
be pasted into shared evidence as it is.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import sys
from importlib import metadata

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

# The versions stored with each AI answer, so a result can be traced to the
# prompt that produced it. A new prompt version module goes here too.
PROMPT_VERSIONS = (
    ("app.services.tutor_guardrails", "TUTOR_PROMPT_VERSION"),
    ("app.services.tutor_guardrails", "TUTOR_TALK_VERSION"),
    ("app.services.free_text_classifier", "PROMPT_VERSION"),
    ("app.services.generation", "VERIFY_PROMPT_VERSION"),
    ("app.services.image_captioning", "CAPTION_PROMPT_VERSION"),
    ("app.services.session_summary", "SUMMARY_PROMPT_VERSION"),
    ("app.services.session_summary", "STUDENT_PROMPT_VERSION"),
)


def prompt_versions() -> dict[str, str]:
    import importlib

    found = {}
    for module, name in PROMPT_VERSIONS:
        value = getattr(importlib.import_module(module), name, None)
        found[f"{module.rsplit('.', 1)[1]}.{name}"] = value if isinstance(value, str) else "missing"
    return found


def switches(settings) -> dict[str, bool]:  # noqa: ANN001
    """Every true/false setting. Nothing else, so no value can be a secret."""
    return {
        name: value
        for name in sorted(type(settings).model_fields)
        if isinstance(value := getattr(settings, name), bool)
    }


def packages() -> dict[str, object]:
    installed = sorted(
        f"{dist.metadata['Name'].lower()}=={dist.version}" for dist in metadata.distributions()
    )
    return {
        "count": len(installed),
        "sha256": hashlib.sha256("\n".join(installed).encode()).hexdigest(),
    }


def migration_head() -> list[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return sorted(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())


async def migration_current(url: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text("select version_num from alembic_version"))
            return sorted(row[0] for row in rows)
    finally:
        await engine.dispose()


async def models(settings) -> dict[str, str]:  # noqa: ANN001
    """The configured model names, with the digest Ollama holds for each."""
    wanted = {"chat": settings.ollama_model, "embedding": settings.embedding_model}
    base = settings.ollama_base_url.rstrip("/").removesuffix("/v1")
    digests: dict[str, str] = {}
    reached = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{base}/api/tags")
            response.raise_for_status()
            reached = True
            for model in response.json().get("models", []):
                name, digest = model.get("name"), model.get("digest")
                if isinstance(name, str) and isinstance(digest, str):
                    digests[name] = digest
                    digests.setdefault(name.removesuffix(":latest"), digest)
    except (httpx.HTTPError, ValueError):
        pass
    if not reached:
        # Unreachable and not downloaded are different faults; say which.
        return {role: f"{name} (could not reach Ollama)" for role, name in wanted.items()}
    return {
        role: f"{name}@{digests[name][:12]}" if name in digests else f"{name} (not pulled)"
        for role, name in wanted.items()
    }


async def main() -> None:
    settings = get_settings()
    current = await migration_current(settings.database_url)
    head = migration_head()
    record = {
        "release_sha": settings.clip_release_sha,
        "environment": settings.clip_env,
        "python": platform.python_version(),
        "packages": packages(),
        "migration": {"current": current, "head": head, "at_head": current == head},
        "models": await models(settings),
        "prompt_versions": prompt_versions(),
        "switches": switches(settings),
    }
    json.dump(record, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    asyncio.run(main())
