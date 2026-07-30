"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.clip_log_level)
log = logging.getLogger("clip")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.teams_configured:
        log.warning("Teams credentials set but the adapter is not implemented yet")
    else:
        log.info("Running without Teams integration")
    yield


app = FastAPI(
    title="C.L.I.P API",
    description="Cognitive Learning Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "env": settings.clip_env,
        "teams_configured": settings.teams_configured,
    }
