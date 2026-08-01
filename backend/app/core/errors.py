"""Application error types and the handlers that render them.

Every error leaves the API in the same envelope so the frontend has one code
path for failures:

    {"error": {"code": "...", "message": "...", "detail": {...}},
     "request_id": "..."}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("clip.errors")


class ClipError(Exception):
    """Base class for errors we raise deliberately.

    `code` is a stable machine-readable string. The frontend switches on it, so
    changing one is a breaking API change.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(ClipError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(ClipError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationError(ClipError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"


class AuthenticationError(ClipError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"


class PermissionError_(ClipError):
    """Authenticated but not allowed. Named with a trailing underscore to avoid
    shadowing the builtin."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class ConsentRequiredError(ClipError):
    """Raised when a monitoring feature is used without a recorded consent row.

    Distinct from FORBIDDEN because the client should show a consent prompt
    rather than an access-denied message.
    """

    status_code = status.HTTP_403_FORBIDDEN
    code = "CONSENT_REQUIRED"


class ServiceUnavailableError(ClipError):
    """A dependency we do not control is down: Postgres, Ollama, Teams."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"


class NotImplementedYetError(ClipError):
    """A route whose contract is frozen but whose owner has not built it yet."""

    status_code = status.HTTP_501_NOT_IMPLEMENTED
    code = "NOT_IMPLEMENTED"


def not_implemented(owner: str, phase: str) -> NotImplementedYetError:
    return NotImplementedYetError(
        f"Not implemented yet. Owner: {owner}, scheduled for {phase}.",
        {"owner": owner, "phase": phase},
    )


def _envelope(request: Request, code: str, message: str, detail: dict[str, Any]) -> dict:
    return {
        "error": {"code": code, "message": message, "detail": detail},
        "request_id": getattr(request.state, "request_id", None),
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ClipError)
    async def _clip_error(request: Request, exc: ClipError) -> JSONResponse:
        if exc.status_code >= 500:
            log.exception("%s: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's errors contain exception objects that json cannot encode.
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                request, "VALIDATION_ERROR", "Request validation failed", {"errors": errors}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "NOT_ALLOWED"}
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                request, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail), {}
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak a stack trace or driver message to a student's browser.
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(request, "INTERNAL_ERROR", "An unexpected error occurred", {}),
        )
