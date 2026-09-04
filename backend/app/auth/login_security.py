"""Persistent production login lockout state backed by the audit log."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.store import ACCOUNT_LOCK_DURATION, MAX_FAILED_LOGIN_ATTEMPTS
from app.models.audit_log import AuditLog
from app.models.user import User

LOGIN_FAILED_ACTION = "LOGIN_FAILED"
ACCOUNT_LOCKED_ACTION = "ACCOUNT_LOCKED"
LOGIN_SUCCEEDED_ACTION = "LOGIN_SUCCEEDED"


class PersistentLoginSecurityStore:
    """Share login-failure and lockout state across production workers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _lock_user(self, user_id: UUID) -> None:
        """Serialize login-security updates for one user."""

        await self.session.execute(
            select(User.user_id).where(User.user_id == user_id).with_for_update()
        )

    async def _latest_action(
        self,
        user_id: UUID,
        action_type: str,
    ) -> datetime | None:
        result = await self.session.execute(
            select(AuditLog.timestamp)
            .where(
                AuditLog.user_id == user_id,
                AuditLog.action_type == action_type,
            )
            .order_by(AuditLog.timestamp.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def is_locked(self, user_id: UUID) -> bool:
        """Return whether the latest account lock is still active."""

        locked_at = await self._latest_action(
            user_id,
            ACCOUNT_LOCKED_ACTION,
        )

        if locked_at is None:
            return False

        return datetime.now(UTC) < locked_at + ACCOUNT_LOCK_DURATION

    async def record_failed_login(
        self,
        user_id: UUID,
        ip_address: str,
    ) -> bool:
        """Persist a failure and return whether the account is now locked."""

        await self._lock_user(user_id)

        # Re-check after obtaining the row lock so concurrent workers cannot
        # create independent lockout counters.
        if await self.is_locked(user_id):
            return True

        now = datetime.now(UTC)
        cutoff = now - ACCOUNT_LOCK_DURATION

        latest_success = await self._latest_action(
            user_id,
            LOGIN_SUCCEEDED_ACTION,
        )

        since = cutoff

        if latest_success is not None and latest_success > since:
            since = latest_success

        self.session.add(
            AuditLog(
                user_id=user_id,
                action_type=LOGIN_FAILED_ACTION,
                ip_address=ip_address,
            )
        )

        await self.session.flush()

        result = await self.session.execute(
            select(func.count(AuditLog.log_id)).where(
                AuditLog.user_id == user_id,
                AuditLog.action_type == LOGIN_FAILED_ACTION,
                AuditLog.timestamp >= since,
            )
        )

        failure_count = int(result.scalar_one())

        locked = failure_count >= MAX_FAILED_LOGIN_ATTEMPTS

        if locked:
            self.session.add(
                AuditLog(
                    user_id=user_id,
                    action_type=ACCOUNT_LOCKED_ACTION,
                    ip_address=ip_address,
                )
            )

            await self.session.flush()

        # Failed login endpoints raise AuthenticationError. get_db() would
        # otherwise roll this security state back with the request.
        await self.session.commit()

        return locked

    async def record_successful_login(
        self,
        user_id: UUID,
        ip_address: str,
    ) -> None:
        """Record success so earlier failed attempts no longer count."""

        await self._lock_user(user_id)

        self.session.add(
            AuditLog(
                user_id=user_id,
                action_type=LOGIN_SUCCEEDED_ACTION,
                ip_address=ip_address,
            )
        )

        await self.session.flush()
        await self.session.commit()
