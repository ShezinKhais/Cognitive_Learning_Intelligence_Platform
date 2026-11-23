"""Best-effort pop-ups and chat cards through the public-cloud Teams connector.

- Students are told when a checkpoint opens, with how long it stays open.
- The session's lecturer gets short updates while they teach: an alert, how
  many answered a checkpoint, engagement dropping across the class. Each is
  a pop-up only they see, so they need not stop sharing to open C.L.I.P.
  Updates carry counts and course content, never a student's name, since a
  pop-up can appear on a shared screen. They are spaced out, and the
  lecturer can mute them for the rest of the class.
- Whoever joins a meeting whose class is running gets a pop-up opening
  C.L.I.P.
- When the class ends, the meeting chat is told where students can review it.

Only authenticated Teams meeting events may establish an outbound reference.
The bounded background tasks never hold the classroom's question lock.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.session import Session
from app.models.student import Student
from app.models.teams_meeting_link import MAX_TEAMS_MEETING_ID_LENGTH, TeamsMeetingLink
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User
from app.schemas.meetings import TeamsActivity, activity_meeting_id
from app.services import class_glance
from app.services.course_membership import students_on

log = logging.getLogger("clip.teams.notifications")


def connector_url(value: str) -> str:
    """Do not send bot credentials to arbitrary activity/body URLs or redirects."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "smba.trafficmanager.net"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or ".." in parsed.path
        or "%" in parsed.path
        or "\\" in value
    ):
        raise ValueError("Unsupported Teams connector service URL")
    return value.rstrip("/") + "/"


def panel_url(base: str, session_id: UUID, path: str = "/teams/meeting") -> str:
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("TEAMS_APP_BASE_URL must be a public HTTPS origin")
    query = urlencode({"sessionId": str(session_id)})
    return f"{parsed.scheme}://{parsed.netloc}{path}?{query}"


def update_url(base: str, session_id: UUID) -> str:
    """The lecturer's update pop-up: the latest updates and the mute switch."""
    return panel_url(base, session_id, "/lecturer/teams/update")


def review_url(base: str, session_id: UUID) -> str:
    """A student's review of a class that has ended."""
    return panel_url(base, session_id, f"/student/reviews/{session_id}").split("?", 1)[0]


def seconds_left(closes_at: float) -> int:
    return max(0, int(closes_at - time.time()))


def _title(text: str) -> str:
    return text if len(text) <= MAX_TITLE else text[: MAX_TITLE - 3].rstrip() + "..."


def checkpoint_card(target: str, course: str, title: str, seconds: int | None = None) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "body": [
            {
                "type": "TextBlock",
                "text": "C.L.I.P live checkpoint",
                "weight": "Bolder",
                "size": "Medium",
            },
            {"type": "TextBlock", "text": f"{course} — {title}", "wrap": True},
            {
                "type": "TextBlock",
                "text": "Open the student panel to respond to the current checkpoint."
                + (f" It closes in about {seconds} seconds." if seconds else ""),
                "wrap": True,
            },
        ],
        "actions": [
            {
                # A dialog over the meeting, from the bot's task/fetch answer.
                # An OpenUrl deep link opened the app's tab instead, which
                # takes the user out of the meeting view.
                "type": "Action.Submit",
                "title": "Answer now",
                "data": {"msteams": {"type": "task/fetch"}, "clip": "checkpoint", "target": target},
            }
        ],
    }


# The in-meeting dialog a checkpoint opens in, in pixels. Big enough for a
# question and four options without scrolling, small enough to leave the
# lecture in view around it.
CHECKPOINT_DIALOG = {"width": 480, "height": 520}


def checkpoint_dialog(target: str) -> dict:
    """The answer to a checkpoint card's task/fetch: open the checkpoint in a
    dialog over the meeting."""
    return {
        "task": {
            "type": "continue",
            "value": {
                "title": "C.L.I.P checkpoint",
                "url": target,
                "fallbackUrl": target,
                **CHECKPOINT_DIALOG,
            },
        }
    }


def checkpoint_dialog_for(activity_value: object, settings: Settings) -> dict | None:
    """The dialog for a checkpoint card's "Answer now", or None when the press
    is not one. The page opened is always our own checkpoint view for the
    session named in the card, rebuilt here, never a URL taken from it."""
    data = activity_value.get("data") if isinstance(activity_value, dict) else None
    if not isinstance(data, dict) or data.get("clip") != "checkpoint":
        return None
    target = data.get("target")
    if not isinstance(target, str):
        return None
    try:
        session_id = UUID(parse_qs(urlsplit(target).query).get("sessionId", [""])[0])
        own = panel_url(settings.teams_app_base_url, session_id) + "&view=dialog"
    except ValueError:
        return None
    return checkpoint_dialog(own)


def ended_card(target: str, course: str, title: str) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "body": [
            {
                "type": "TextBlock",
                "text": "C.L.I.P class ended",
                "weight": "Bolder",
                "size": "Medium",
            },
            {"type": "TextBlock", "text": f"{course}: {title}", "wrap": True},
            {
                "type": "TextBlock",
                "text": "Students can look back over the checkpoints and their answers in C.L.I.P.",
                "wrap": True,
            },
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "Review the class", "url": target}],
    }


async def remember_reference(db, activity: TeamsActivity, settings: Settings) -> None:
    """Keep where the bot can post into this activity's meeting.

    Called only after BotAuthenticator.verify AND authorize succeeded, for
    every activity, not only a meeting's start and end: a lecturer often links
    the session after the meeting has started, and the reference is kept per
    meeting so it is there whenever the link is made.
    """
    if not settings.teams_notifications_enabled:
        return
    data = activity.channel_data or {}
    tenant = data.get("tenant") or {}
    conversation = (activity.model_extra or {}).get("conversation") or {}
    meeting_id = activity_meeting_id(activity)
    conversation_id = conversation.get("id") if isinstance(conversation, dict) else None
    tenant_id = tenant.get("id") if isinstance(tenant, dict) else None
    if (
        not isinstance(meeting_id, str)
        or not meeting_id
        or len(meeting_id) > MAX_TEAMS_MEETING_ID_LENGTH
        or not isinstance(conversation_id, str)
        or not conversation_id
        or len(conversation_id) > 512
        or not isinstance(tenant_id, str)
        or tenant_id.lower() != settings.tenant_id.lower()
    ):
        return
    try:
        service = connector_url(activity.service_url)
    except ValueError:
        log.warning("Teams notification reference rejected: unsupported connector")
        return
    reference = {
        "service_url": service,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
    }
    await db.execute(
        insert(TeamsMeetingReference)
        .values(meeting_id=meeting_id, **reference)
        .on_conflict_do_update(
            index_elements=[TeamsMeetingReference.meeting_id],
            set_={**reference, "seen_at": func.now()},
        )
    )
    await db.commit()


@dataclass(frozen=True)
class CheckpointNotice:
    session_id: UUID
    closes_at: float
    question_id: UUID


@dataclass(frozen=True)
class AlertNotice:
    """An update for the session's lecturer. The pop-up's title is the update
    itself, and it opens the update page, which lists the latest ones.

    An update that is not an alert waits delay seconds first, and is dropped
    if another pop-up went out meanwhile: a checkpoint closing and the alert
    it raises are one interruption, not two."""

    session_id: UUID
    closes_at: float
    title: str = "C.L.I.P alert: open the panel"
    delay: float = 0
    queued_at: float = 0


@dataclass(frozen=True)
class WelcomeNotice:
    """Open C.L.I.P for people in the meeting: these, by Entra id to Teams id,
    or everyone in the meeting chat when None."""

    session_id: UUID
    closes_at: float
    people: dict[str, str] | None = None


@dataclass(frozen=True)
class EndedNotice:
    session_id: UUID
    closes_at: float


@dataclass(frozen=True)
class LastCallNotice:
    """A checkpoint about to close, for the students who have not answered."""

    session_id: UUID
    question_id: UUID
    user_ids: frozenset[UUID]
    closes_at: float


@dataclass
class LecturerUpdate:
    at: datetime
    kind: str
    text: str


# What the update page lists.
RECENT_UPDATES = 8


@dataclass
class _Updates:
    recent: deque = field(default_factory=lambda: deque(maxlen=RECENT_UPDATES))
    muted: bool = False
    popped_at: float | None = None
    sent: dict[str, float] = field(default_factory=dict)


# How long an alert pop-up may take to go out, and the least time between two
# for one session, so a burst of alerts is one interruption, not several.
ALERT_SEND_SECONDS = 30
ALERT_COOLDOWN_SECONDS = 60
# The least time between two updates of one kind. Any update also waits a
# minute after the pop-up before it. Engagement moves slowly, so it is told
# less often.
UPDATE_COOLDOWN_SECONDS = {"checkpoint": 60, "attention": 300}
UPDATE_DELAY_SECONDS = 3
# How many classes' updates are held at once.
MAX_TRACKED_SESSIONS = 200
# A rejoin within this long does not pop C.L.I.P up again.
WELCOME_COOLDOWN_SECONDS = 300
MAX_TITLE = 120


class TeamsNotifications:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()
        self.slots = asyncio.Semaphore(2)
        self.token_lock = asyncio.Lock()
        self.token = ""
        self.token_until = 0.0
        self.token_identity: tuple[str, str, str] | None = None
        self.alerted_at: dict[UUID, float] = {}
        self.updates: OrderedDict[UUID, _Updates] = OrderedDict()
        self.welcomed: dict[tuple[UUID, str], float] = {}

    def enqueue(self, session_id: UUID, question_id: UUID, closes_at: float) -> None:
        self._start(CheckpointNotice(session_id, closes_at, question_id))

    def enqueue_alert(self, session_id: UUID, message: str | None = None) -> None:
        """Tell the session's lecturer a class alert was raised, at most once a
        minute per session."""
        self.update_lecturer(session_id, "alert", message or "C.L.I.P alert: open the panel")

    def _held(self, session_id: UUID) -> _Updates:
        held = self.updates.get(session_id)
        if held is None:
            held = self.updates[session_id] = _Updates()
            while len(self.updates) > MAX_TRACKED_SESSIONS:
                self.updates.popitem(last=False)
        self.updates.move_to_end(session_id)
        return held

    def update_lecturer(self, session_id: UUID, kind: str, text: str) -> None:
        """Keep an update for the lecturer's update page, and pop it up unless
        they muted updates or were told something moments ago."""
        held = self._held(session_id)
        held.recent.appendleft(LecturerUpdate(datetime.now(UTC), kind, _title(text)))
        if held.muted:
            return
        now = time.monotonic()
        if kind == "alert":
            last = self.alerted_at.get(session_id)
            if last is not None and now - last < ALERT_COOLDOWN_SECONDS:
                return
            notice = AlertNotice(session_id, time.time() + ALERT_SEND_SECONDS, _title(text))
            if self._start(notice):
                self.alerted_at = {
                    sid: at
                    for sid, at in self.alerted_at.items()
                    if now - at < ALERT_COOLDOWN_SECONDS
                }
                self.alerted_at[session_id] = now
                held.popped_at = now
            return
        last = held.sent.get(kind)
        if (
            last is not None
            and now - last < UPDATE_COOLDOWN_SECONDS.get(kind, ALERT_COOLDOWN_SECONDS)
        ) or (held.popped_at is not None and now - held.popped_at < ALERT_COOLDOWN_SECONDS):
            return
        notice = AlertNotice(
            session_id,
            time.time() + UPDATE_DELAY_SECONDS + ALERT_SEND_SECONDS,
            _title(text),
            delay=UPDATE_DELAY_SECONDS,
            queued_at=now,
        )
        if self._start(notice):
            held.sent[kind] = now

    def recent_updates(self, session_id: UUID) -> tuple[bool, list[LecturerUpdate]]:
        """Whether the lecturer muted updates, and the latest, newest first."""
        held = self.updates.get(session_id)
        return (held.muted, list(held.recent)) if held else (False, [])

    def mute(self, session_id: UUID, muted: bool) -> None:
        self._held(session_id).muted = muted

    def forget(self, session_id: UUID) -> None:
        """A class has ended: nothing more is told about it."""
        self.updates.pop(session_id, None)
        self.alerted_at.pop(session_id, None)
        self.welcomed = {key: at for key, at in self.welcomed.items() if key[0] != session_id}

    def enqueue_welcome(self, session_id: UUID, people: dict[str, str] | None = None) -> None:
        """Open C.L.I.P for people joining a running class, once each in a while."""
        if people is not None:
            now = time.monotonic()
            self.welcomed = {
                key: at for key, at in self.welcomed.items() if now - at < WELCOME_COOLDOWN_SECONDS
            }
            people = {
                aad: teams_id
                for aad, teams_id in people.items()
                if (session_id, aad) not in self.welcomed
            }
            if not people:
                return
            for aad in people:
                self.welcomed[(session_id, aad)] = now
        self._start(WelcomeNotice(session_id, time.time() + ALERT_SEND_SECONDS, people))

    def enqueue_last_call(
        self, session_id: UUID, question_id: UUID, user_ids: set[UUID], closes_at: float
    ) -> None:
        """Remind the students who have not answered that a checkpoint closes
        in a few seconds. Sent only while there is time for them to answer."""
        if get_settings().teams_last_call_enabled and user_ids:
            self._start(LastCallNotice(session_id, question_id, frozenset(user_ids), closes_at))

    def enqueue_class_ended(self, session_id: UUID) -> None:
        self.forget(session_id)
        self._start(EndedNotice(session_id, time.time() + ALERT_SEND_SECONDS))

    def _start(
        self,
        notice: CheckpointNotice | AlertNotice | WelcomeNotice | EndedNotice | LastCallNotice,
    ) -> bool:
        settings = get_settings()
        if not settings.teams_notifications_enabled:
            return False
        if len(self.tasks) >= 100:
            log.warning("Teams notification skipped: queue full")
            return False
        task = asyncio.create_task(self._run(notice))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return True

    async def shutdown(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(
        self,
        notice: CheckpointNotice | AlertNotice | WelcomeNotice | EndedNotice | LastCallNotice,
    ) -> None:
        what = {
            AlertNotice: "alert",
            WelcomeNotice: "welcome",
            EndedNotice: "class ended",
            LastCallNotice: "last call",
        }.get(type(notice), "checkpoint")
        try:
            if isinstance(notice, AlertNotice) and notice.delay:
                await asyncio.sleep(notice.delay)
                held = self.updates.get(notice.session_id)
                if (
                    held is None
                    or held.muted
                    or (held.popped_at is not None and held.popped_at > notice.queued_at)
                ):
                    return
                held.popped_at = time.monotonic()
            async with self.slots:
                remaining = notice.closes_at - time.time()
                if remaining <= 0:
                    return
                async with asyncio.timeout(min(remaining, 12)):
                    if isinstance(notice, AlertNotice):
                        await self.send_alert(notice, get_settings())
                    elif isinstance(notice, WelcomeNotice):
                        await self.send_welcome(notice, get_settings())
                    elif isinstance(notice, EndedNotice):
                        await self.send_ended(notice, get_settings())
                    elif isinstance(notice, LastCallNotice):
                        await self.send_last_call(notice, get_settings())
                    else:
                        await self.send(notice, get_settings())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                self.token_until = 0
            log.warning("Teams %s notification refused: HTTP %s", what, exc.response.status_code)
        except Exception:
            # Neither credentials nor connector response bodies belong in logs.
            log.warning("Teams %s notification failed; WebSocket delivery remains available", what)

    async def access_token(self, client: httpx.AsyncClient, settings: Settings) -> str:
        async with self.token_lock:
            authority = settings.teams_bot_token_tenant or settings.tenant_id
            identity = (settings.client_id, authority, settings.client_secret)
            if identity == self.token_identity and time.monotonic() < self.token_until:
                return self.token
            tenant = quote(authority, safe="")
            response = await client.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "scope": "https://api.botframework.com/.default",
                },
            )
            response.raise_for_status()
            body = response.json()
            token = body["access_token"]
            if not isinstance(token, str) or not token:
                raise ValueError("Missing bot token")
            self.token = token
            self.token_until = time.monotonic() + max(0, min(float(body["expires_in"]), 3600) - 60)
            self.token_identity = identity
            return token

    async def send(self, notice: CheckpointNotice, settings: Settings) -> None:
        if not settings.teams_configured:
            return
        dialog_target = panel_url(settings.teams_app_base_url, notice.session_id) + "&view=dialog"
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(TeamsMeetingLink, Session, Course, TeamsMeetingReference)
                    .join(Session, Session.session_id == TeamsMeetingLink.session_id)
                    .join(
                        TeamsMeetingReference,
                        TeamsMeetingReference.meeting_id == TeamsMeetingLink.meeting_id,
                    )
                    .join(Course, Course.id == Session.course_id)
                    .join(DeliveredQuestion, DeliveredQuestion.session_id == Session.session_id)
                    .where(
                        Session.session_id == notice.session_id,
                        Session.status == "active",
                        Session.paused_at.is_(None),
                        DeliveredQuestion.question_id == notice.question_id,
                        DeliveredQuestion.closed_at.is_(None),
                        DeliveredQuestion.closes_at > datetime.now(UTC),
                    )
                )
            ).first()
            if row is None:
                return
            link, session, course, reference = row
            if reference.tenant_id != settings.tenant_id:
                return
            base = connector_url(reference.service_url)
            students = set(
                (
                    await db.scalars(
                        select(TeamsUserMapping.teams_user_id)
                        .join(User, User.user_id == TeamsUserMapping.user_id)
                        .join(Student, Student.user_id == User.user_id)
                        .where(
                            TeamsUserMapping.tenant_id == settings.tenant_id,
                            Student.student_id.in_(students_on(session.course_id)),
                            User.role == "student",
                            User.active.is_(True),
                        )
                    )
                ).all()
            )
            title, code = session.title, course.code
            meeting_id, conversation_id = link.meeting_id, reference.conversation_id
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            token = await self.access_token(client, settings)
            headers = {"Authorization": f"Bearer {token}"}
            recipients = await _meeting_members(client, base, headers, conversation_id, students)
            if not recipients or time.time() >= notice.closes_at:
                return
            # The pop-up is the notification: a dialog over the meeting that
            # the student answers in and closes, with the lecture still on
            # screen. A chat message as well made Teams announce it twice, and
            # its link opened the app's full tab, minimising the meeting.
            try:
                await _targeted_popup(
                    client,
                    base,
                    headers,
                    meeting_id,
                    recipients,
                    title=(
                        "New C.L.I.P checkpoint: about "
                        f"{seconds_left(notice.closes_at)} seconds to answer"
                    ),
                    url=dialog_target,
                    closes_at=notice.closes_at,
                    **CHECKPOINT_DIALOG,
                )
                return
            except httpx.HTTPStatusError as exc:
                # Without the meeting notification permission the pop-up is
                # refused. The chat card opens the same dialog instead.
                log.warning(
                    "Teams checkpoint pop-up refused (%s); posting the chat card",
                    exc.response.status_code,
                )
            if time.time() >= notice.closes_at:
                return
            response = await client.post(
                base + f"v3/conversations/{quote(conversation_id, safe='')}/activities",
                headers=headers,
                json={
                    "type": "message",
                    "text": "New checkpoint: answer it without leaving the meeting",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": checkpoint_card(
                                dialog_target,
                                code,
                                title,
                                seconds_left(notice.closes_at),
                            ),
                        }
                    ],
                },
            )
            response.raise_for_status()

    async def send_alert(self, notice: AlertNotice, settings: Settings) -> None:
        """Pop the lecturer's panel up in the meeting. Only the session's own
        lecturer is told, and only once their Teams account is linked."""
        if not settings.teams_configured:
            return
        target = update_url(settings.teams_app_base_url, notice.session_id)
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(TeamsMeetingLink, TeamsMeetingReference, TeamsUserMapping)
                    .join(Session, Session.session_id == TeamsMeetingLink.session_id)
                    .join(
                        TeamsMeetingReference,
                        TeamsMeetingReference.meeting_id == TeamsMeetingLink.meeting_id,
                    )
                    .join(User, User.user_id == Session.instructor_id)
                    .join(TeamsUserMapping, TeamsUserMapping.user_id == User.user_id)
                    .where(
                        Session.session_id == notice.session_id,
                        Session.status == "active",
                        User.active.is_(True),
                        TeamsUserMapping.tenant_id == settings.tenant_id,
                    )
                )
            ).first()
            if row is None:
                return
            link, reference, mapping = row
            if reference.tenant_id != settings.tenant_id:
                return
            base = connector_url(reference.service_url)
            meeting_id, conversation_id = link.meeting_id, reference.conversation_id
            lecturer = {mapping.teams_user_id}
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            token = await self.access_token(client, settings)
            headers = {"Authorization": f"Bearer {token}"}
            # Only while they are in this meeting's roster.
            recipients = await _meeting_members(client, base, headers, conversation_id, lecturer)
            if not recipients:
                return
            await _targeted_popup(
                client,
                base,
                headers,
                meeting_id,
                recipients,
                title=notice.title,
                url=target,
                closes_at=notice.closes_at,
            )

    async def send_welcome(self, notice: WelcomeNotice, settings: Settings) -> None:
        """Open C.L.I.P for people in a running class, except its lecturer."""
        if not settings.teams_configured:
            return
        target = panel_url(settings.teams_app_base_url, notice.session_id)
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(TeamsMeetingLink, TeamsMeetingReference, Session)
                    .join(Session, Session.session_id == TeamsMeetingLink.session_id)
                    .join(
                        TeamsMeetingReference,
                        TeamsMeetingReference.meeting_id == TeamsMeetingLink.meeting_id,
                    )
                    .where(
                        Session.session_id == notice.session_id,
                        Session.status == "active",
                    )
                )
            ).first()
            if row is None:
                return
            link, reference, session = row
            if reference.tenant_id != settings.tenant_id:
                return
            # Someone joining a class already under way is told how much has
            # happened, so they know to catch up in the panel.
            asked = 0
            if notice.people is not None:
                asked = (
                    await db.scalar(
                        select(func.count())
                        .select_from(DeliveredQuestion)
                        .where(DeliveredQuestion.session_id == notice.session_id)
                    )
                    or 0
                )
            lecturer = await db.scalar(
                select(TeamsUserMapping.teams_user_id).where(
                    TeamsUserMapping.user_id == session.instructor_id,
                    TeamsUserMapping.tenant_id == settings.tenant_id,
                )
            )
            base = connector_url(reference.service_url)
            meeting_id, conversation_id = link.meeting_id, reference.conversation_id
        skip = (lecturer or "").lower()
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            token = await self.access_token(client, settings)
            headers = {"Authorization": f"Bearer {token}"}
            if notice.people is None:
                everyone = await _chat_members(client, base, headers, conversation_id)
                recipients = {teams_id for aad, teams_id in everyone.items() if aad.lower() != skip}
            else:
                recipients = {
                    teams_id
                    for aad, teams_id in notice.people.items()
                    if aad.lower() != skip and teams_id.startswith("29:")
                }
            if not recipients:
                return
            await _targeted_popup(
                client,
                base,
                headers,
                meeting_id,
                recipients,
                title=(
                    f"You joined late: {asked} checkpoint{'s' if asked != 1 else ''} so far. "
                    "Open C.L.I.P to catch up"
                    if asked
                    else "C.L.I.P is running in this class"
                ),
                url=target,
                closes_at=notice.closes_at,
            )

    async def send_last_call(self, notice: LastCallNotice, settings: Settings) -> None:
        """Pop the checkpoint up again for the students who have not answered,
        a few seconds before it closes."""
        if not settings.teams_configured:
            return
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(TeamsMeetingLink, TeamsMeetingReference)
                    .join(Session, Session.session_id == TeamsMeetingLink.session_id)
                    .join(
                        TeamsMeetingReference,
                        TeamsMeetingReference.meeting_id == TeamsMeetingLink.meeting_id,
                    )
                    .join(DeliveredQuestion, DeliveredQuestion.session_id == Session.session_id)
                    .where(
                        Session.session_id == notice.session_id,
                        Session.status == "active",
                        Session.paused_at.is_(None),
                        DeliveredQuestion.question_id == notice.question_id,
                        DeliveredQuestion.closed_at.is_(None),
                    )
                )
            ).first()
            if row is None:
                return
            link, reference = row
            if reference.tenant_id != settings.tenant_id:
                return
            entra = set(
                (
                    await db.scalars(
                        select(TeamsUserMapping.teams_user_id).where(
                            TeamsUserMapping.tenant_id == settings.tenant_id,
                            TeamsUserMapping.user_id.in_(notice.user_ids),
                        )
                    )
                ).all()
            )
            base = connector_url(reference.service_url)
            meeting_id, conversation_id = link.meeting_id, reference.conversation_id
        if not entra:
            return
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            token = await self.access_token(client, settings)
            headers = {"Authorization": f"Bearer {token}"}
            recipients = await _meeting_members(client, base, headers, conversation_id, entra)
            if not recipients or time.time() >= notice.closes_at:
                return
            await _targeted_popup(
                client,
                base,
                headers,
                meeting_id,
                recipients,
                title=f"Last call: {seconds_left(notice.closes_at)} seconds left on the checkpoint",
                url=panel_url(settings.teams_app_base_url, notice.session_id) + "&view=dialog",
                closes_at=notice.closes_at,
                **CHECKPOINT_DIALOG,
            )

    async def send_ended(self, notice: EndedNotice, settings: Settings) -> None:
        """Tell the meeting chat where students can review the class."""
        if not settings.teams_configured:
            return
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(TeamsMeetingReference, Session, Course)
                    .join(
                        TeamsMeetingLink,
                        TeamsMeetingLink.meeting_id == TeamsMeetingReference.meeting_id,
                    )
                    .join(Session, Session.session_id == TeamsMeetingLink.session_id)
                    .join(Course, Course.id == Session.course_id)
                    .where(Session.session_id == notice.session_id, Session.status == "ended")
                )
            ).first()
            if row is None:
                return
            reference, session, course = row
            if reference.tenant_id != settings.tenant_id:
                return
            base = connector_url(reference.service_url)
            conversation_id = reference.conversation_id
            card = ended_card(
                review_url(settings.teams_app_base_url, notice.session_id),
                course.code,
                session.title,
            )
            # The lecturer's summary is extra: if any of it cannot be read, the
            # students' card still goes out.
            summary = lecturer = meeting_id = None
            try:
                summary = _title(await class_glance.class_summary(db, session))
                lecturer = await db.scalar(
                    select(TeamsUserMapping.teams_user_id).where(
                        TeamsUserMapping.user_id == session.instructor_id,
                        TeamsUserMapping.tenant_id == settings.tenant_id,
                    )
                )
                meeting_id = await db.scalar(
                    select(TeamsMeetingLink.meeting_id).where(
                        TeamsMeetingLink.session_id == notice.session_id
                    )
                )
            except Exception:
                log.warning("Could not build the class summary for the lecturer")
        if summary:
            # Kept on the update page as well, under the class's other updates.
            self._held(notice.session_id).recent.appendleft(
                LecturerUpdate(datetime.now(UTC), "summary", summary)
            )
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            token = await self.access_token(client, settings)
            if summary and lecturer and meeting_id:
                headers = {"Authorization": f"Bearer {token}"}
                try:
                    present = await _meeting_members(
                        client, base, headers, conversation_id, {lecturer}
                    )
                    if present:
                        await _targeted_popup(
                            client,
                            base,
                            headers,
                            meeting_id,
                            present,
                            title=summary,
                            url=update_url(settings.teams_app_base_url, notice.session_id),
                            closes_at=notice.closes_at,
                        )
                except httpx.HTTPError:
                    log.warning("Teams class summary pop-up was not delivered")
            response = await client.post(
                base + f"v3/conversations/{quote(conversation_id, safe='')}/activities",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "type": "message",
                    "text": "This class has ended. Students can review it in C.L.I.P",
                    "attachments": [
                        {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
                    ],
                },
            )
            response.raise_for_status()


async def _meeting_members(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    conversation_id: str,
    aad_ids: set[str],
) -> set[str]:
    """Resolve Entra IDs to Teams 29: IDs using the authenticated meeting's roster."""
    members = await _chat_members(client, base, headers, conversation_id)
    return {teams_id for aad, teams_id in members.items() if aad in aad_ids}


async def _chat_members(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    conversation_id: str,
) -> dict[str, str]:
    """Everyone in the meeting chat, as Entra ID to Teams 29: ID."""
    recipients: dict[str, str] = {}
    continuation = None
    for _ in range(10):
        response = await client.get(
            base + f"v3/conversations/{quote(conversation_id, safe='')}/pagedmembers",
            headers=headers,
            params={
                "pageSize": 100,
                **({"continuationToken": continuation} if continuation else {}),
            },
        )
        response.raise_for_status()
        body = response.json()
        for member in body.get("members", []):
            user_id = member.get("id", "")
            aad = member.get("aadObjectId")
            if (
                isinstance(aad, str)
                and aad
                and isinstance(user_id, str)
                and user_id.startswith("29:")
            ):
                recipients[aad] = user_id
        continuation = body.get("continuationToken")
        if not continuation:
            break
    return recipients


async def _targeted_popup(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    meeting_id: str,
    recipients: set[str],
    *,
    title: str,
    url: str,
    closes_at: float,
    width: int = 400,
    height: int = 300,
) -> None:
    """Open url in a pop-up over the meeting for these members only, fifty
    at a time. It is a dialog on top of the meeting, so the lecture stays in
    view."""
    ordered = sorted(recipients)
    for offset in range(0, len(ordered), 50):
        if time.time() >= closes_at:
            return
        response = await client.post(
            base + f"v1/meetings/{quote(meeting_id, safe='')}/notification",
            headers=headers,
            json={
                "type": "targetedMeetingNotification",
                "value": {
                    "recipients": ordered[offset : offset + 50],
                    "surfaces": [
                        {
                            "surface": "meetingStage",
                            "contentType": "task",
                            "content": {
                                "value": {
                                    "height": str(height),
                                    "width": str(width),
                                    "title": title,
                                    "url": url,
                                }
                            },
                        }
                    ],
                },
            },
        )
        response.raise_for_status()
        if response.status_code == 207:
            log.warning("Teams notification partially delivered")


notifications = TeamsNotifications()
