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
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.student_repository import StudentRepository

log = logging.getLogger("clip.accommodations")


class Accommodations:
    def __init__(self) -> None:
        self._accommodated: set[UUID] = set()

    def set(self, user_id: UUID, accommodated: bool) -> None:
        if accommodated:
            self._accommodated.add(user_id)
        else:
            self._accommodated.discard(user_id)

    def members(self) -> frozenset[UUID]:
        return frozenset(self._accommodated)

    def __contains__(self, user_id: object) -> bool:
        return user_id in self._accommodated


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
