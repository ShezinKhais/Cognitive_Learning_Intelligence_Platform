"""Starting a class from a Teams meeting nobody prepared a session for.

Owner: General CS, Phase 8. When a lecturer opens C.L.I.P in a meeting with
no session linked, the side panel asks "Is this a class?". The course and
title are guessed from the meeting's title ("CSIT321 Week 5 Lecture" is
CSIT321, titled as the meeting is); with no code in the title, the course is
the first one the lecturer teaches. Saying yes creates the session, links
the meeting and starts it, so engagement is recorded from then on. The
same organiser rule as linking applies.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import Settings
from app.models.course import Course
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.schemas.meetings import MeetingClassStart, MeetingClassSuggestion
from app.schemas.session import MAX_TITLE_LENGTH, SessionCreateRequest, SessionOut
from app.services import meeting_organiser, session_lifecycle
from app.services.course_detection import detect_course, normalise
from app.services.course_membership import my_courses

log = logging.getLogger("clip.meetings.unscheduled")


async def meeting_title(
    db: AsyncSession, meeting_id: str, settings: Settings, fetch=None
) -> str | None:
    """The meeting's title from Teams, or None when Teams cannot say."""
    if not settings.teams_notifications_enabled:
        return None
    reference = await db.scalar(
        select(TeamsMeetingReference).where(TeamsMeetingReference.meeting_id == meeting_id)
    )
    if reference is None:
        return None
    fetch = fetch or meeting_organiser.fetch_meeting_details
    try:
        body = await fetch(settings, reference.service_url, meeting_id)
    except (httpx.HTTPError, ValueError) as exc:
        log.info("meeting title for %s unavailable: %s", meeting_id, type(exc).__name__)
        return None
    details = body.get("details") if isinstance(body, dict) else None
    title = details.get("title") if isinstance(details, dict) else None
    return title.strip()[:MAX_TITLE_LENGTH] if isinstance(title, str) and title.strip() else None


async def suggest(
    db: AsyncSession, principal: Principal, title: str | None
) -> MeetingClassSuggestion:
    """The course and session title to offer for a meeting with this title."""
    courses = (await db.execute(select(Course.id, Course.code))).all()
    known = {normalise(code): course_id for course_id, code in courses}
    code_of = {course_id: code for course_id, code in courses}
    mine = await my_courses(db, principal)
    found = detect_course(title or "", [], known)
    course_code = code_of[found] if found else (mine[0].code if mine else None)
    return MeetingClassSuggestion(
        meeting_title=title,
        course_code=course_code,
        title=title or "Class",
        courses=mine,
    )


async def start_class(
    db: AsyncSession,
    principal: Principal,
    meeting_id: str,
    payload: MeetingClassStart,
    settings: Settings,
    check_organiser=meeting_organiser.require_organiser,
) -> SessionOut:
    """Create the session, link it to this meeting and start it."""
    await check_organiser(db, principal, meeting_id, settings)
    created = await session_lifecycle.create_session(
        db, principal, SessionCreateRequest(course_code=payload.course_code, title=payload.title)
    )
    await session_lifecycle.link_meeting(db, principal, meeting_id, created.id)
    started = await session_lifecycle.start_session(db, principal, created.id)
    log.info("unscheduled class %s started in meeting %s", created.id, meeting_id)
    return started
