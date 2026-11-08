"""What the bot says back when someone writes to it, or adds it to a chat.

Owner: General CS, Phase 4.

The bot is not a chat assistant: the tutor lives in the side panel, where
C.L.I.P knows who the student is and what they have consented to. In chat it
answers two things, in words anyone in the meeting may see:

- "help", or anything it does not recognise: what C.L.I.P is and where to
  open it.
- "status": whether this meeting has a C.L.I.P session, and whether the class
  is waiting, running or over. The course code and session title are already
  on every checkpoint card in the same chat, so nothing new is disclosed.

Called only after the activity's token, channel and tenant were checked. A
reply that fails is logged and dropped: Teams would retry an error, and the
message it answers has already been read.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.course import Course
from app.models.session import Session
from app.schemas.meetings import TeamsActivity
from app.services.meeting_directory import meetings
from app.services.teams_meeting_flow import card_action
from app.services.teams_notifications import connector_url, notifications

log = logging.getLogger("clip.teams.replies")

HELP = (
    "**C.L.I.P** checks how the class is following, during the lecture.\n\n"
    "- **Students:** open C.L.I.P from the meeting's side panel. Checkpoints also "
    "pop up there while the class runs.\n"
    "- **Lecturer:** open the side panel to link a session and run the class. The "
    "full dashboard opens from the Lecturer tab.\n\n"
    "Write **@CLIP status** to see whether this meeting has a C.L.I.P session. "
    "In a meeting chat, start with **@CLIP** and pick it from the list, or the "
    "bot does not see the message."
)
WELCOME = "C.L.I.P is ready in this meeting.\n\n" + HELP

STATUS_WORDS = {
    "prepared": "is ready and waits for the lecturer to start it",
    "active": "is running now. Open the side panel to take part",
    "paused": "is paused",
    "ending": "is ending",
    "ended": "has ended. Students can review it from My Learning",
    "cancelled": "was cancelled",
}

_MENTION = re.compile(r"<at>.*?</at>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def command_of(text: str | None) -> str:
    """The word someone wrote to the bot, with its @mention and markup removed."""
    cleaned = _TAGS.sub(" ", _MENTION.sub(" ", text or "")).strip().lower()
    return cleaned.split()[0] if cleaned else ""


def _meeting_id(activity: TeamsActivity) -> str | None:
    meeting = (activity.channel_data or {}).get("meeting")
    meeting_id = meeting.get("id") if isinstance(meeting, dict) else None
    return meeting_id if isinstance(meeting_id, str) and meeting_id else None


async def status_text(db: AsyncSession, meeting_id: str | None) -> str:
    if meeting_id is None:
        return "Write **@CLIP status** in a meeting's chat to see that meeting's C.L.I.P session."
    session_id = await meetings.directory.session_for(meeting_id)
    row = (
        (
            await db.execute(
                select(Session.title, Session.status, Session.paused_at, Course.code)
                .join(Course, Course.id == Session.course_id)
                .where(Session.session_id == session_id)
            )
        ).first()
        if session_id is not None
        else None
    )
    if row is None:
        return (
            "This meeting has no C.L.I.P session yet. The organiser links one from the "
            "C.L.I.P side panel."
        )
    title, status, paused_at, code = row
    state = "paused" if status == "active" and paused_at is not None else status
    return f"**{code}: {title}** {STATUS_WORDS.get(state, 'is ' + state)}."


def _bot_added(activity: TeamsActivity) -> bool:
    extra = activity.model_extra or {}
    recipient = extra.get("recipient") or {}
    bot_id = recipient.get("id") if isinstance(recipient, dict) else None
    added = extra.get("membersAdded") or []
    return bool(bot_id) and any(
        isinstance(member, dict) and member.get("id") == bot_id for member in added
    )


async def reply_text(db: AsyncSession, activity: TeamsActivity) -> str | None:
    """What to say to this activity, or None to stay quiet."""
    if activity.type == "message":
        if card_action(activity) is not None:
            # A press on one of C.L.I.P's cards, answered by teams_meeting_flow.
            return None
        if command_of((activity.model_extra or {}).get("text")) == "status":
            return await status_text(db, _meeting_id(activity))
        return HELP
    if activity.type == "conversationUpdate" and _bot_added(activity):
        return WELCOME
    return None


async def post_reply(settings: Settings, activity: TeamsActivity, text: str) -> None:
    extra = activity.model_extra or {}
    conversation = extra.get("conversation") or {}
    conversation_id = conversation.get("id") if isinstance(conversation, dict) else None
    if not isinstance(conversation_id, str) or not conversation_id:
        return
    base = connector_url(activity.service_url)
    path = f"v3/conversations/{quote(conversation_id, safe='')}/activities"
    reply_to = extra.get("id")
    if activity.type == "message" and isinstance(reply_to, str) and reply_to:
        path += f"/{quote(reply_to, safe='')}"
    async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
        token = await notifications.access_token(client, settings)
        response = await client.post(
            base + path,
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "message", "textFormat": "markdown", "text": text},
        )
        response.raise_for_status()


async def answer(
    db: AsyncSession, activity: TeamsActivity, settings: Settings, post=post_reply
) -> None:
    """Reply to a message, or greet a chat the bot was just added to."""
    try:
        text = await reply_text(db, activity)
        if text is not None:
            await post(settings, activity, text)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("bot reply not sent: %s", type(exc).__name__)
