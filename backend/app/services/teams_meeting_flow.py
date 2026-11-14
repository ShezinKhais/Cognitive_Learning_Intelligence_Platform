"""What the bot does in a meeting beyond starting and ending its linked class.

Owner: General CS, Phase 8.

- A meeting that starts with no session linked becomes a class without
  anyone opening C.L.I.P. The bot reads the meeting's title and organiser
  from Teams. When the title names a course the organiser teaches
  ("CSIT321 Week 5"), the class starts and a card in the meeting chat says
  so, with a "Not a class" button that ends it again. When it names none,
  the card asks "Is this a class?" and lists the organiser's courses.
- Only the organiser's press on a card counts. Teams says who pressed it,
  and the organiser is read from Teams again for every press, so nothing
  the card itself carries is trusted beyond which button it was.
- Someone joining a meeting whose class is running gets a pop-up that opens
  C.L.I.P for them, so a student does not have to find the side panel. Joins
  and leaves are kept as Teams roster events (teams_roster_sync), by Teams
  identity only, with no display names. Retention removes them with the
  other roster syncs.

Called only after the activity's token, channel and tenant were checked. A
failure is logged and dropped: Teams would retry an error, and a retry
cannot fix one.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import Settings
from app.core.errors import ClipError
from app.models.session import Session
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.teams_user_mapping import TeamsUserMapping
from app.repositories.teams_roster_repository import (
    RosterParticipantInput,
    TeamsRosterRepository,
)
from app.schemas.meetings import MeetingEventIn, MeetingEventKind, TeamsActivity
from app.schemas.session import MAX_TITLE_LENGTH, SessionStatus
from app.services import meeting_organiser, session_lifecycle
from app.services.course_detection import codes_in
from app.services.course_membership import my_courses
from app.services.meeting_directory import meetings
from app.services.teams_notifications import connector_url, notifications

log = logging.getLogger("clip.teams.meetings")

# The key an Adaptive Card's submit data carries to say it is one of ours.
CARD_ACTION = "clip"
START, NOT_A_CLASS, DISMISS = "start", "not_class", "dismiss"

PARTICIPANT_EVENTS = {
    "application/vnd.microsoft.meetingParticipantJoin": "participant_joined",
    "application/vnd.microsoft.meetingParticipantLeave": "participant_left",
}

# Teams may deliver a meeting's start twice. One card is enough.
OFFER_MEMORY_SECONDS = 600
# The most members one participant event is read for.
MAX_EVENT_MEMBERS = 100


class MeetingFlow:
    def __init__(self) -> None:
        self.offered: dict[str, float] = {}

    def first_offer(self, meeting_id: str) -> bool:
        now = time.monotonic()
        self.offered = {
            mid: at for mid, at in self.offered.items() if now - at < OFFER_MEMORY_SECONDS
        }
        if meeting_id in self.offered:
            return False
        self.offered[meeting_id] = now
        return True


flow = MeetingFlow()


# -- cards -------------------------------------------------------------------


def _card(body: list[dict], actions: list[dict] | None = None) -> dict:
    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "version": "1.5",
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def _text(text: str, **style: Any) -> dict:
    return {"type": "TextBlock", "text": text, "wrap": True, **style}


def _submit(title: str, data: dict[str, str]) -> dict:
    return {"type": "Action.Submit", "title": title, "data": data}


def started_card(code: str, title: str, session_id: UUID) -> dict:
    return _card(
        [
            _text("C.L.I.P class started", weight="Bolder", size="Medium"),
            _text(f"{code}: {title}"),
            _text(
                "Students: C.L.I.P opens for you as you join. You can also open it from "
                "the meeting's side panel.",
                isSubtle=True,
            ),
        ],
        [_submit("Not a class", {CARD_ACTION: NOT_A_CLASS, "session": str(session_id)})],
    )


def question_card(courses: list[tuple[str, str]]) -> dict:
    """Is this a class? courses is (code, name) for each course the organiser teaches."""
    return _card(
        [
            _text("Is this a class?", weight="Bolder", size="Medium"),
            _text(
                "C.L.I.P could not tell the course from the meeting's title. The organiser "
                "can start the class here."
            ),
            {
                "type": "Input.ChoiceSet",
                "id": "course",
                "label": "Course",
                "isRequired": True,
                "value": courses[0][0],
                "choices": [{"title": f"{code}: {name}", "value": code} for code, name in courses],
            },
        ],
        [
            _submit("Start the class", {CARD_ACTION: START}),
            _submit("Not a class", {CARD_ACTION: DISMISS}),
        ],
    )


def outcome_card(text: str) -> dict:
    return _card([_text("C.L.I.P", weight="Bolder"), _text(text)])


# -- talking to the meeting chat ---------------------------------------------


async def post_card(
    settings: Settings, service_url: str, conversation_id: str, card: dict, replace: str | None
) -> None:
    """Post a card to the chat, or put it in place of the card replace names."""
    base = connector_url(service_url)
    path = f"v3/conversations/{quote(conversation_id, safe='')}/activities"
    activity: dict[str, Any] = {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }
    async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
        token = await notifications.access_token(client, settings)
        headers = {"Authorization": f"Bearer {token}"}
        if replace:
            response = await client.put(
                base + f"{path}/{quote(replace, safe='')}",
                headers=headers,
                json={**activity, "id": replace},
            )
        else:
            response = await client.post(base + path, headers=headers, json=activity)
        response.raise_for_status()


def _conversation(activity: TeamsActivity) -> str | None:
    conversation = (activity.model_extra or {}).get("conversation") or {}
    found = conversation.get("id") if isinstance(conversation, dict) else None
    return found if isinstance(found, str) and found else None


def _chat_meeting_id(activity: TeamsActivity) -> str | None:
    meeting = (activity.channel_data or {}).get("meeting")
    found = meeting.get("id") if isinstance(meeting, dict) else None
    return found if isinstance(found, str) and found else None


# -- who the organiser is -----------------------------------------------------


async def _meeting(
    db: AsyncSession, meeting_id: str, settings: Settings, fetch
) -> tuple[str | None, str | None]:
    """The meeting's organiser (Entra object id, lower case) and title, as
    Teams reports them now."""
    reference = await db.scalar(
        select(TeamsMeetingReference).where(TeamsMeetingReference.meeting_id == meeting_id)
    )
    if reference is None or reference.tenant_id.lower() != settings.tenant_id.lower():
        return None, None
    body = await fetch(settings, reference.service_url, meeting_id)
    details = body.get("details") if isinstance(body, dict) else None
    title = details.get("title") if isinstance(details, dict) else None
    title = title.strip()[:MAX_TITLE_LENGTH] if isinstance(title, str) and title.strip() else None
    return meeting_organiser.organiser_of(body), title


async def _staff_for(
    db: AsyncSession, aad_object_id: str, meeting_id: str, settings: Settings
) -> Principal | None:
    """The C.L.I.P lecturer this Teams account belongs to, if they can be acted for."""
    user_id = await db.scalar(
        select(TeamsUserMapping.user_id).where(
            TeamsUserMapping.tenant_id == settings.tenant_id,
            func.lower(TeamsUserMapping.teams_user_id) == aad_object_id.lower(),
        )
    )
    if user_id is None:
        return None
    return await session_lifecycle.act_as_lecturer(db, user_id, meeting_id, settings)


def course_in_title(title: str | None, codes: list[str]) -> str | None:
    """The one course of these the title names, or None."""
    named = codes_in(title or "")
    found = [code for code in codes if codes_in(code) & named]
    return found[0] if len(found) == 1 else None


# -- a meeting starts with nothing linked -------------------------------------


async def meeting_started_unlinked(
    db: AsyncSession,
    activity: TeamsActivity,
    meeting_id: str,
    settings: Settings,
    *,
    fetch=meeting_organiser.fetch_meeting_details,
    post=post_card,
) -> None:
    """Start the class the title names, or ask whether this is one."""
    conversation_id = _conversation(activity)
    if (
        not settings.teams_notifications_enabled
        or conversation_id is None
        or not flow.first_offer(meeting_id)
    ):
        return
    try:
        organiser, title = await _meeting(db, meeting_id, settings, fetch)
        principal = await _staff_for(db, organiser, meeting_id, settings) if organiser else None
        if principal is None:
            log.info(
                "meeting %s started unlinked; its organiser has no C.L.I.P account", meeting_id
            )
            return
        courses = await my_courses(db, principal)
        if not courses:
            return
        code = course_in_title(title, [course.code for course in courses])
        if code is None:
            await post(
                settings,
                activity.service_url,
                conversation_id,
                question_card([(course.code, course.name) for course in courses]),
                None,
            )
            return
        started = await _start(db, principal, meeting_id, code, title)
        await post(
            settings,
            activity.service_url,
            conversation_id,
            started_card(code, started.title, started.id),
            None,
        )
    except (ClipError, httpx.HTTPError, ValueError) as exc:
        await db.rollback()
        log.warning("meeting %s start was not offered: %s", meeting_id, type(exc).__name__)


async def _start(
    db: AsyncSession, principal: Principal, meeting_id: str, code: str, title: str | None
):
    started = await session_lifecycle.handle_meeting_event(
        db,
        principal,
        MeetingEventIn(
            kind=MeetingEventKind.STARTED,
            meeting_id=meeting_id,
            course_code=code,
            title=title or session_lifecycle.MEETING_TITLE,
        ),
    )
    notifications.enqueue_welcome(started.id)
    return started


# -- a press on one of the cards ----------------------------------------------


def card_action(activity: TeamsActivity) -> dict | None:
    """The submit data of a press on one of C.L.I.P's cards, or None."""
    if activity.type != "message":
        return None
    value = (activity.model_extra or {}).get("value")
    if isinstance(value, dict) and isinstance(value.get(CARD_ACTION), str):
        return value
    return None


async def answer_card(
    db: AsyncSession,
    activity: TeamsActivity,
    settings: Settings,
    *,
    fetch=meeting_organiser.fetch_meeting_details,
    post=post_card,
) -> None:
    """Act on the organiser's press of Start the class or Not a class."""
    value = card_action(activity)
    meeting_id = _chat_meeting_id(activity)
    conversation_id = _conversation(activity)
    sender = (activity.model_extra or {}).get("from") or {}
    pressed_by = sender.get("aadObjectId") if isinstance(sender, dict) else None
    replace = (activity.model_extra or {}).get("replyToId")
    if (
        value is None
        or meeting_id is None
        or conversation_id is None
        or not isinstance(pressed_by, str)
        or not settings.teams_notifications_enabled
    ):
        return
    try:
        organiser, title = await _meeting(db, meeting_id, settings, fetch)
        if organiser is None or organiser != pressed_by.lower():
            log.info("a C.L.I.P card in meeting %s was pressed by someone else", meeting_id)
            return
        principal = await _staff_for(db, organiser, meeting_id, settings)
        if principal is None:
            return
        text = await _apply(db, principal, meeting_id, value, title)
        if text is not None:
            await post(
                settings,
                activity.service_url,
                conversation_id,
                outcome_card(text),
                replace if isinstance(replace, str) and replace else None,
            )
    except (ClipError, httpx.HTTPError, ValueError) as exc:
        await db.rollback()
        log.warning(
            "a C.L.I.P card press in %s was not applied: %s", meeting_id, type(exc).__name__
        )


async def _apply(
    db: AsyncSession, principal: Principal, meeting_id: str, value: dict, title: str | None
) -> str | None:
    action = value.get(CARD_ACTION)
    if action == START:
        code = value.get("course")
        mine = {course.code for course in await my_courses(db, principal)}
        if not isinstance(code, str) or code not in mine:
            return None
        started = await _start(db, principal, meeting_id, code, title)
        return (
            f"{code}: {started.title} has started. Students can open C.L.I.P from the side panel."
        )
    if action == DISMISS:
        return "Not a class. The organiser can still start one from the C.L.I.P side panel."
    if action == NOT_A_CLASS:
        session_id = await meetings.directory.session_for(meeting_id)
        if session_id is None or str(session_id) != value.get("session"):
            return None
        row = await db.get(Session, session_id)
        if row is None or row.instructor_id != principal.user_id:
            return None
        if row.status not in session_lifecycle.FINISHED:
            await session_lifecycle.end_session(db, principal, session_id)
        return "Not a class. C.L.I.P has ended the session it started for this meeting."
    return None


# -- people joining and leaving -----------------------------------------------


async def participants_changed(
    db: AsyncSession, activity: TeamsActivity, settings: Settings
) -> None:
    """Keep a join or leave, and open C.L.I.P for whoever joins a running class."""
    kind = PARTICIPANT_EVENTS.get(activity.name or "") if activity.type == "event" else None
    meeting_id = _chat_meeting_id(activity)
    if kind is None or meeting_id is None or not settings.teams_notifications_enabled:
        return
    session_id = await meetings.directory.session_for(meeting_id)
    if session_id is None:
        return
    value = (activity.model_extra or {}).get("value") or {}
    members = value.get("members") if isinstance(value, dict) else None
    people: list[tuple[str, str]] = []
    for member in (members if isinstance(members, list) else [])[:MAX_EVENT_MEMBERS]:
        user = member.get("user") if isinstance(member, dict) else None
        if not isinstance(user, dict):
            continue
        teams_id, aad = user.get("id"), user.get("aadObjectId")
        if (
            isinstance(teams_id, str)
            and teams_id.startswith("29:")
            and isinstance(aad, str)
            and aad
        ):
            people.append((teams_id, aad.lower()))
    if not people:
        return
    event_id = (activity.model_extra or {}).get("id")
    try:
        if isinstance(event_id, str) and event_id:
            await TeamsRosterRepository(db).record_sync(
                meeting_id=meeting_id,
                session_id=session_id,
                source_event_id=event_id[:256],
                event_type=kind,
                participants=[
                    RosterParticipantInput(tenant_id=settings.tenant_id, teams_user_id=aad)
                    for _, aad in people
                ],
            )
            await db.commit()
    except ClipError as exc:
        await db.rollback()
        log.warning("a roster event for %s was not kept: %s", meeting_id, type(exc).__name__)
    if kind == "participant_joined":
        status = await db.scalar(select(Session.status).where(Session.session_id == session_id))
        if status == SessionStatus.ACTIVE.value:
            notifications.enqueue_welcome(session_id, {aad: teams_id for teams_id, aad in people})
