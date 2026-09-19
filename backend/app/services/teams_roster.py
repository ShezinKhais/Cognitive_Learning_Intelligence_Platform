"""Roster reconciliation: Teams meeting participants against the admin roster.

Owner: BBIS, Phase 4. Matching is email-first (exact) and falls back to
fuzzy display-name matching against the course's enrolled students, reusing
app.services.timetable_import.match_names -- the same function Cyber 2's
Phase 1 admin console uses for this exact purpose, so a Teams display name
and an uploaded roster name are resolved by the same rule.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import Student
from app.models.user import User
from app.repositories.teams_repository import TeamsRepository
from app.repositories.user_repository import UserRepository
from app.schemas.teams import RosterSyncSummary, TeamsParticipant
from app.services.timetable_import import match_names


async def _enrolled_users_by_name(db: AsyncSession, course_id: uuid.UUID) -> dict[str, User]:
    result = await db.execute(
        select(User)
        .join(Student, Student.user_id == User.user_id)
        .where(Student.course_id == course_id)
    )
    return {user.name: user for user in result.scalars().all()}


async def sync_roster(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    course_id: uuid.UUID,
    participants: list[TeamsParticipant],
) -> RosterSyncSummary:
    teams_repo = TeamsRepository(db)
    user_repo = UserRepository(db)
    enrolled_by_name = await _enrolled_users_by_name(db, course_id)

    matched = 0
    unmatched = 0
    duplicates = 0
    unmatched_names: list[str] = []

    for participant in participants:
        user: User | None = None
        if participant.email:
            user = await user_repo.get_by_email(str(participant.email))

        if user is None and enrolled_by_name:
            _unmatched, matches = match_names(
                [participant.display_name], list(enrolled_by_name.keys())
            )
            matched_name = matches.get(participant.display_name)
            if matched_name:
                user = enrolled_by_name[matched_name]

        if user is None:
            unmatched += 1
            unmatched_names.append(participant.display_name)
            continue

        _mapping, conflict = await teams_repo.link_user(
            teams_user_id=participant.teams_user_id,
            user_id=user.user_id,
            display_name=participant.display_name,
        )
        if conflict:
            duplicates += 1
        else:
            matched += 1

    await teams_repo.record_roster_sync(
        session_id=session_id,
        matched=matched,
        unmatched=unmatched,
        duplicates=duplicates,
    )

    return RosterSyncSummary(
        matched=matched,
        unmatched=unmatched,
        duplicates=duplicates,
        unmatched_names=unmatched_names,
    )
