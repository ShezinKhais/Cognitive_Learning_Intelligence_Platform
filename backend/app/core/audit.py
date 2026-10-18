"""Reusable audit logging for successful state-changing endpoints.

The address a request came from is deliberately not recorded: nothing uses it,
and it would be personal data kept without a purpose.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import signature
from typing import Any, ParamSpec, TypeVar

from sqlalchemy import event

from app.models.audit_log import AuditLog

P = ParamSpec("P")
R = TypeVar("R")

log = logging.getLogger("clip.audit")


def audit_action(
    action_type: str,
    *,
    commit: bool = False,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Audit a successful state-changing endpoint.

    The audit record joins the endpoint's transaction, so the change and its
    record are kept or lost together. With commit=True that transaction is
    committed here, before the response, for an endpoint that must act on
    the change only once it is durable (it does so from an after-commit
    hook, which never runs if the change or its audit record fails).
    """

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
            settings: Any = bound.arguments.get("settings")

            if principal is None:
                raise RuntimeError("Audited endpoints must receive a principal parameter.")

            user_id = getattr(principal, "user_id", None)

            if user_id is None:
                raise RuntimeError("Audited endpoints require a principal with user_id.")

            if settings is not None and settings.is_production:
                if db is None:
                    raise RuntimeError("Production audited endpoints must receive a db parameter.")

                recorded = False

                def record(session: Any) -> None:
                    nonlocal recorded
                    # A released savepoint is not the durable endpoint commit.
                    if getattr(session, "in_nested_transaction", lambda: False)():
                        return
                    if recorded:
                        return
                    session.add(
                        AuditLog(
                            user_id=user_id,
                            action_type=action_type,
                        )
                    )
                    recorded = True

                # Services may commit before returning (and then announce live
                # changes). Join that commit, not a second transaction afterward.
                sync = getattr(db, "sync_session", None)
                if sync is not None:
                    event.listen(sync, "before_commit", record)
                try:
                    result = await func(*args, **kwargs)
                    record(db)
                    await db.flush()
                    if commit:
                        await db.commit()
                finally:
                    if sync is not None:
                        event.remove(sync, "before_commit", record)
            else:
                result = await func(*args, **kwargs)
                log.info(
                    "audit_event=%s user_id=%s",
                    action_type,
                    user_id,
                )

            return result

        # Read by the test that every state-changing route is audited.
        wrapper.audit_action_type = action_type  # type: ignore[attr-defined]
        return wrapper

    return decorator
