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
from uuid import UUID

from sqlalchemy import event

from app.models.audit_log import AuditLog

P = ParamSpec("P")
R = TypeVar("R")

log = logging.getLogger("clip.audit")


# Path values that name what was acted on without being an id.
_NAMED_TARGETS = {"code": "course", "course_code": "course", "meeting_id": "meeting"}


def _target(arguments: dict[str, Any]) -> tuple[str | None, UUID | None, dict[str, str]]:
    """What the request acted on, from the endpoint's own arguments.

    The last id in the signature is the most specific (a question within a
    material), so it is the target and the others go in details. A course is
    named by its code, which goes in details with the target type. Bodies
    are never read: they can hold personal data, and the target is in the
    path for every audited route that has one.
    """
    ids = [
        (name, value)
        for name, value in arguments.items()
        if name.endswith("_id") and isinstance(value, UUID)
    ]
    details = {name: str(value) for name, value in ids[:-1]}
    target_type: str | None = None
    target_id: UUID | None = None
    if ids:
        name, target_id = ids[-1]
        target_type = name.removesuffix("_id")
    for name, kind in _NAMED_TARGETS.items():
        value = arguments.get(name)
        if isinstance(value, str) and value:
            details[name] = value[:100]
            target_type = target_type or kind
    return target_type, target_id, details


def _created_id(result: Any) -> UUID | None:
    """The id of what a create endpoint returned, when it has one."""
    for attr in ("id", "session_id", "material_id", "user_id"):
        value = getattr(result, attr, None)
        if isinstance(value, UUID):
            return value
    return None


def _kind(result: Any, action_type: str) -> str:
    """What a create returned: SessionOut is a session. Otherwise the first
    word of the action, SESSION_CREATED being a session too."""
    name = type(result).__name__
    if name.endswith("Out") and len(name) > 3:
        return "".join(
            f"_{c.lower()}" if c.isupper() and i else c.lower()
            for i, c in enumerate(name.removesuffix("Out"))
        )[:50]
    return action_type.split("_")[0].lower()


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
            target_type, target_id, details = _target(dict(bound.arguments))

            if user_id is None:
                raise RuntimeError("Audited endpoints require a principal with user_id.")

            if settings is not None and settings.is_production:
                if db is None:
                    raise RuntimeError("Production audited endpoints must receive a db parameter.")

                recorded = False
                entry: AuditLog | None = None

                def record(session: Any) -> None:
                    nonlocal recorded, entry
                    # A released savepoint is not the durable endpoint commit.
                    if getattr(session, "in_nested_transaction", lambda: False)():
                        return
                    if recorded:
                        return
                    entry = AuditLog(
                        user_id=user_id,
                        action_type=action_type,
                        target_type=target_type,
                        target_id=target_id,
                        details=details or None,
                    )
                    session.add(entry)
                    recorded = True

                # Services may commit before returning (and then announce live
                # changes). Join that commit, not a second transaction afterward.
                sync = getattr(db, "sync_session", None)
                if sync is not None:
                    event.listen(sync, "before_commit", record)
                try:
                    result = await func(*args, **kwargs)
                    if target_id is None:
                        # A create names its target only in what it returns.
                        target_id = _created_id(result)
                        if target_id is not None:
                            target_type = _kind(result, action_type)
                            if entry is not None:
                                # Recorded already, by a commit inside the
                                # service. The record kept its place in that
                                # commit; its target follows with the request's.
                                entry.target_type, entry.target_id = target_type, target_id
                                db.add(entry)
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
                    "audit_event=%s user_id=%s target=%s:%s",
                    action_type,
                    user_id,
                    target_type,
                    target_id,
                )

            return result

        # Read by the test that every state-changing route is audited.
        wrapper.audit_action_type = action_type  # type: ignore[attr-defined]
        return wrapper

    return decorator
