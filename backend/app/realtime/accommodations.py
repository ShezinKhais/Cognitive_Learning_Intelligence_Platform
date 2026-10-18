"""Which connected students have a recorded accommodation.

Owner: Cyber 1, Phase 6. Engagement scoring (services/engagement.py) leaves out
the signals that assume one way of interacting for these students. Only the
*fact* of an accommodation is kept here: the text of Student.accessibility_need
is never read into this module, logged, scored or sent to anyone, lecturers
included.

A student whose record cannot be read is treated as accommodated, never the
other way: the safe mistake is to flag someone less, not more.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.student_repository import StudentRepository

log = logging.getLogger("clip.accommodations")


def _today() -> date:
    return datetime.now(UTC).date()


class Accommodations:
    """Each accommodated student with the last day it applies, None for no end.
    A day that has passed counts as no accommodation, so a class running past
    the end of a granted consideration stops honouring it without a rejoin."""

    def __init__(self) -> None:
        self._accommodated: dict[UUID, date | None] = {}

    def set(self, user_id: UUID, accommodated: bool, *, until: date | None = None) -> None:
        if accommodated:
            self._accommodated[user_id] = until
        else:
            self._accommodated.pop(user_id, None)

    def grant(self, user_id: UUID, until: date | None) -> None:
        """Add an accommodation without shortening one already held."""
        if user_id in self:
            held = self._accommodated[user_id]
            if held is None or (until is not None and held >= until):
                return
        self._accommodated[user_id] = until

    def members(self) -> frozenset[UUID]:
        return frozenset(user for user in self._accommodated if user in self)

    def __contains__(self, user_id: object) -> bool:
        if user_id not in self._accommodated:
            return False
        until = self._accommodated[user_id]  # type: ignore[index]
        return until is None or until >= _today()


async def has_accommodation(db: AsyncSession, user_id: UUID) -> bool:
    """Whether the student has an accommodation on record. True when that
    cannot be established. Reads the record only to test it for content."""
    try:
        student = await StudentRepository(db).get_by_user_id(user_id)
    except Exception:
        log.warning("could not check accommodation for a student; assuming one")
        return True
    if student is None:
        return False
    need = student.accessibility_need
    return need is not None and bool(need.strip())
