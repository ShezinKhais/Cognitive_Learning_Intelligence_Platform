"""Shared response shapes.

Frozen contract. Changing a field here breaks every consumer, so treat edits as
a version bump rather than a tweak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str = Field(
        description="Stable machine-readable code. Switch on this, not on message."
    )
    message: str = Field(description="Human-readable, safe to show a user.")
    detail: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = Field(
        default=None,
        description="Correlates with the X-Request-ID header and the server logs.",
    )


class Page(BaseModel, Generic[T]):
    """Offset pagination. No endpoint is expected to exceed a few thousand rows
    for a single course, so cursors are not worth the complexity."""

    items: list[T]
    total: int
    limit: int
    offset: int


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None
    latency_ms: float | None = None


class HealthResponse(BaseModel):
    """Liveness. Answers "is the process up", nothing more."""

    status: str = "ok"
    env: str
    version: str
    teams_configured: bool


class ReadinessResponse(BaseModel):
    """Readiness. Answers "can this instance actually serve traffic".

    Returns 503 when a required dependency is down so a load balancer or the
    frontend can distinguish "starting" from "broken".
    """

    ready: bool
    checked_at: datetime
    dependencies: list[DependencyStatus]
