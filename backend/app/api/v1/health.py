"""Liveness and readiness.

Liveness answers "is the process running". Readiness answers "can it actually
serve traffic", which means checking the dependencies we cannot control.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.api.deps import AppSettings, DbSession
from app.core.config import get_settings
from app.schemas.common import DependencyStatus, HealthResponse, ReadinessResponse

router = APIRouter(tags=["meta"])

APP_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health(settings: AppSettings) -> HealthResponse:
    return HealthResponse(
        env=settings.clip_env,
        version=APP_VERSION,
        teams_configured=settings.teams_configured,
    )


async def _check_database(db: DbSession) -> DependencyStatus:
    started = time.perf_counter()
    try:
        await db.execute(text("select 1"))
        extensions = (await db.execute(text("select extname from pg_extension"))).scalars().all()
        missing = {"vector", "pg_trgm"} - set(extensions)
        if missing:
            return DependencyStatus(
                name="postgres",
                ok=False,
                detail=f"missing extensions: {', '.join(sorted(missing))}",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        return DependencyStatus(
            name="postgres",
            ok=True,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception as exc:
        return DependencyStatus(name="postgres", ok=False, detail=type(exc).__name__)


async def _check_ollama() -> DependencyStatus:
    """Confirms the daemon answers and that the configured models are present.

    A running Ollama with the wrong models pulled is a failure mode that looks
    like success until the first question generation.
    """
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/").removesuffix("/v1")
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base}/api/tags")
            response.raise_for_status()
            installed = {m["name"].split(":")[0] for m in response.json().get("models", [])}
        wanted = {settings.ollama_model.split(":")[0], settings.embedding_model.split(":")[0]}
        missing = wanted - installed
        latency = round((time.perf_counter() - started) * 1000, 2)
        if missing:
            return DependencyStatus(
                name="ollama",
                ok=False,
                detail=f"models not pulled: {', '.join(sorted(missing))}",
                latency_ms=latency,
            )
        return DependencyStatus(name="ollama", ok=True, latency_ms=latency)
    except Exception as exc:
        return DependencyStatus(name="ollama", ok=False, detail=type(exc).__name__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"description": "A required dependency is unavailable."}},
)
async def ready(db: DbSession, response: Response) -> ReadinessResponse:
    database, ollama = await asyncio.gather(_check_database(db), _check_ollama())

    # Ollama is reported but does not gate readiness: the live session loop
    # serves pre-generated MCQs and stays useful while the model is down.
    dependencies = [database, ollama]
    ready_now = database.ok

    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        ready=ready_now,
        checked_at=datetime.now(UTC),
        dependencies=dependencies,
    )
