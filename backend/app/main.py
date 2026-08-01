"""FastAPI application entry point."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router, ws_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var

settings = get_settings()
configure_logging(settings.clip_log_level)
log = logging.getLogger("clip")

API_V1 = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.teams_configured:
        log.warning("Teams credentials set but the adapter is not implemented yet")
    else:
        log.info("Running without Teams integration")
    yield


def create_app() -> FastAPI:
    # Interactive docs describe every route, parameter and schema. That is what
    # we want during development and an inventory for an attacker in production.
    expose_docs = not settings.is_production

    app = FastAPI(
        title="C.L.I.P API",
        description=(
            "Cognitive Learning Intelligence Platform.\n\n"
            "Routes returning 501 have a frozen contract but no implementation yet; "
            "the response body names the owning workstream."
        ),
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=f"{API_V1}/openapi.json" if expose_docs else None,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
    )

    # Only the Vite dev server needs this. A Teams tab is an iframe served from
    # our own origin, so its requests are same-origin and never preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        """Tag every request so a user-visible error can be traced to a log line.

        Honours an inbound X-Request-ID so a trace survives the Teams proxy.
        """
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    register_error_handlers(app)

    app.include_router(api_router, prefix=API_V1)
    app.include_router(ws_router)

    return app


app = create_app()
