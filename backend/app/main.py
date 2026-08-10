"""FastAPI application entry point."""

from __future__ import annotations

import logging
import re
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

# An inbound request id is reflected in a response header and formatted into
# every log line for that request, so it has to look like something we could
# have generated. Without this a caller can put a newline in the header and
# write their own lines into the log, which is the one record we keep.
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def resolve_request_id(inbound: str | None) -> str:
    """Return the caller's id if it is safe to trust, otherwise a fresh one."""
    if inbound and REQUEST_ID.fullmatch(inbound):
        return inbound
    return str(uuid.uuid4())


DEV_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().teams_configured:
        log.warning("Teams credentials set but the adapter is not implemented yet")
    else:
        log.info("Running without Teams integration")
    yield


def create_app() -> FastAPI:
    # Read at call time rather than at import, so the environment a test sets up
    # is the environment the app is built from.
    settings = get_settings()

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
    #
    # Not registered in production. Leaving it on would let any page a browser
    # happens to be serving on that port send credentialed requests to the real
    # API and read the replies, in exchange for a convenience nothing in a
    # deployed build uses.
    if not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[DEV_ORIGIN],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        """Tag every request so a user-visible error can be traced to a log line.

        Honours an inbound X-Request-ID so a trace survives the Teams proxy,
        but only when it passes resolve_request_id.
        """
        rid = resolve_request_id(request.headers.get("X-Request-ID"))
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
