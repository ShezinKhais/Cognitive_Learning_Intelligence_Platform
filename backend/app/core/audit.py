"""Reusable audit logging for successful state-changing endpoints."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import signature
from typing import Any, ParamSpec, TypeVar

from fastapi import Request

from app.models.audit_log import AuditLog

P = ParamSpec("P")
R = TypeVar("R")

log = logging.getLogger("clip.audit")


def audit_action(
    action_type: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Audit a successful state-changing endpoint."""

    if not action_type or len(action_type) > 100:
        raise ValueError("action_type must contain between 1 and 100 characters")

    def decorator(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[R]]:
        endpoint_signature = signature(func)

        @wraps(func)
        async def wrapper(
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> R:
            bound = endpoint_signature.bind_partial(*args, **kwargs)

            principal: Any = bound.arguments.get("principal")
            db: Any = bound.arguments.get("db")
            request: Any = bound.arguments.get("request")
            settings: Any = bound.arguments.get("settings")

            if principal is None:
                raise RuntimeError("Audited endpoints must receive a principal parameter.")

            user_id = getattr(principal, "user_id", None)

            if user_id is None:
                raise RuntimeError("Audited endpoints require a principal with user_id.")

            result = await func(*args, **kwargs)

            ip_address = "unknown"

            if isinstance(request, Request) and request.client is not None:
                ip_address = request.client.host

            if settings is not None and settings.is_production:
                if db is None:
                    raise RuntimeError("Production audited endpoints must receive a db parameter.")

                db.add(
                    AuditLog(
                        user_id=user_id,
                        action_type=action_type,
                        ip_address=ip_address,
                    )
                )

                await db.flush()
            else:
                log.info(
                    "audit_event=%s user_id=%s ip_address=%s",
                    action_type,
                    user_id,
                    ip_address,
                )

            return result

        return wrapper

    return decorator
