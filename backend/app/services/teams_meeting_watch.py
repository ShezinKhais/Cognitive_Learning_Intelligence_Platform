"""C.L.I.P in every lecturer's Teams meetings, without anyone adding it.

Owner: General CS, Phase 8.

Until now a lecturer had to open each Teams meeting, add C.L.I.P from Apps,
and either pick the class in the side panel or paste the meeting's link on
the website. With TEAMS_AUTO_JOIN_ENABLED, a background sweep does the first
part for them:

- Every few minutes it reads the coming days of each linked lecturer's
  calendar from Microsoft Graph (Calendars.Read), keeping only Teams
  meetings they organise.
- It installs C.L.I.P into each such meeting's chat
  (TeamsAppInstallation.ReadWriteSelfForChat.All) and pins the C.L.I.P tab
  (TeamsTab.ReadWriteSelfForChat.All), so the meeting has the side panel for
  everyone and the bot hears the meeting start and people join.
- It tells the lecturer in their Teams activity feed (TeamsActivity.Send):
  the class it will run when the meeting's title names one of their
  courses, or a question when it does not. The notice opens the C.L.I.P tab
  in that meeting.

Everything after that is what already happens once C.L.I.P is in a meeting
(teams_meeting_flow): the meeting starting starts the class its title names,
the organiser joining a meeting with no class is asked in a pop-up, and
students joining a running class get C.L.I.P opened for them.

Only meetings a C.L.I.P lecturer organises are touched, and only after
their own account is linked to Teams. A meeting the bot already knows, or
one installed into in this process, is not installed into again, so a
restart costs one conflict per meeting at most. Each step is best effort:
a meeting whose chat Teams has not created yet is tried again on the next
sweep, and a failed notice is not retried.

The tenant's administrator grants the Graph permissions above as
application permissions, with admin consent. Without them the sweep logs
the refusal and does nothing else.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.errors import ClipError
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User
from app.schemas.meetings import meeting_id_for_thread
from app.services import session_lifecycle
from app.services.course_membership import my_courses
from app.services.meeting_organiser import thread_in
from app.services.teams_meeting_flow import course_in_title
from app.services.teams_notifications import panel_url
from app.services.transcript_minutes import graph_token

log = logging.getLogger("clip.teams.watch")

GRAPH = "https://graph.microsoft.com/v1.0"
# The bot's resource-specific permissions in a meeting chat, as the manifest
# asks for them. Granted on install, since nobody is there to consent.
CHAT_PERMISSIONS = [
    ("OnlineMeeting.ReadBasic.Chat", "Application"),
    ("OnlineMeetingParticipant.Read.Chat", "Application"),
    ("OnlineMeetingNotification.Send.Chat", "Application"),
    ("MeetingStage.Write.Chat", "Delegated"),
]
# The tab the side panel opens, as TeamsConfigPage saves it.
TAB_ENTITY = "clip.meeting"
TAB_NAME = "C.L.I.P"
ACTIVITY_TYPE = "meetingReady"
# A meeting installed into in this process is not tried again for this long.
REMEMBER_SECONDS = 7 * 24 * 3600
MAX_EVENTS = 100


@dataclass(frozen=True)
class Meeting:
    thread: str
    subject: str


def upcoming_meetings(events: object) -> list[Meeting]:
    """The Teams meetings in a calendarView page that its owner organises,
    once each: a recurring meeting's occurrences share one chat."""
    found: dict[str, Meeting] = {}
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("isCancelled"):
            continue
        if not event.get("isOrganizer") or not event.get("isOnlineMeeting"):
            continue
        online = event.get("onlineMeeting")
        join_url = online.get("joinUrl") if isinstance(online, dict) else None
        thread = thread_in(join_url) if isinstance(join_url, str) else None
        if thread is None or thread in found:
            continue
        subject = event.get("subject")
        subject = subject.strip()[:200] if isinstance(subject, str) and subject.strip() else ""
        found[thread] = Meeting(thread=thread, subject=subject or "Teams meeting")
    return list(found.values())


def tab_deep_link(app_id: str, thread: str) -> str:
    """A Teams link that opens the C.L.I.P tab in this meeting's chat."""
    context = json.dumps({"chatId": thread, "contextType": "chat"}, separators=(",", ":"))
    return (
        f"https://teams.microsoft.com/l/entity/{quote(app_id, safe='')}/{TAB_ENTITY}?"
        + urlencode({"context": context})
    )


def notice_text(subject: str, code: str | None) -> str:
    if code:
        return f"C.L.I.P is ready in {subject}. It runs as a {code} class when the meeting starts."
    return f"C.L.I.P is ready in {subject}. Is it a class? Open C.L.I.P to set it up."


class Graph:
    """The few Microsoft Graph calls the sweep makes, on fixed paths only."""

    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    async def calendar(self, user: str, start: datetime, end: datetime) -> list:
        response = await self.client.get(
            f"{GRAPH}/users/{quote(user, safe='')}/calendarView",
            headers={**self.headers, "Prefer": 'outlook.timezone="UTC"'},
            params={
                "startDateTime": start.isoformat(),
                "endDateTime": end.isoformat(),
                "$select": "subject,isOnlineMeeting,onlineMeeting,isOrganizer,isCancelled",
                "$top": str(MAX_EVENTS),
            },
        )
        response.raise_for_status()
        body = response.json()
        return body.get("value", []) if isinstance(body, dict) else []

    async def catalog_id(self, external_id: str) -> str | None:
        response = await self.client.get(
            f"{GRAPH}/appCatalogs/teamsApps",
            headers=self.headers,
            params={"$filter": f"externalId eq '{external_id}'"},
        )
        response.raise_for_status()
        apps = response.json().get("value", [])
        found = apps[0].get("id") if apps and isinstance(apps[0], dict) else None
        return found if isinstance(found, str) and found else None

    async def install(self, thread: str, catalog: str) -> bool:
        """Install C.L.I.P into the meeting chat. True when this call did it,
        False when it was already there; an error when the chat is not
        ready or the install is refused."""
        response = await self.client.post(
            f"{GRAPH}/chats/{quote(thread, safe='')}/installedApps",
            headers=self.headers,
            json={
                "teamsApp@odata.bind": f"{GRAPH}/appCatalogs/teamsApps/{catalog}",
                "consentedPermissionSet": {
                    "resourceSpecificPermissions": [
                        {"permissionValue": name, "permissionType": kind}
                        for name, kind in CHAT_PERMISSIONS
                    ]
                },
            },
        )
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True

    async def pin_tab(self, thread: str, catalog: str, base: str) -> None:
        tabs = f"{GRAPH}/chats/{quote(thread, safe='')}/tabs"
        response = await self.client.get(tabs, headers=self.headers, params={"$expand": "teamsApp"})
        response.raise_for_status()
        for tab in response.json().get("value", []):
            app = tab.get("teamsApp") if isinstance(tab, dict) else None
            if isinstance(app, dict) and app.get("id") == catalog:
                return
        content = panel_url(base, UUID(int=0), "/teams/meeting").split("?", 1)[0]
        response = await self.client.post(
            tabs,
            headers=self.headers,
            json={
                "displayName": TAB_NAME,
                "teamsApp@odata.bind": f"{GRAPH}/appCatalogs/teamsApps/{catalog}",
                "configuration": {
                    "entityId": TAB_ENTITY,
                    "contentUrl": content,
                    "websiteUrl": content,
                },
            },
        )
        response.raise_for_status()

    async def notify(self, thread: str, user: str, subject: str, text: str, link: str) -> None:
        response = await self.client.post(
            f"{GRAPH}/chats/{quote(thread, safe='')}/sendActivityNotification",
            headers=self.headers,
            json={
                "topic": {"source": "text", "value": subject, "webUrl": link},
                "activityType": ACTIVITY_TYPE,
                "previewText": {"content": text},
                "recipient": {
                    "@odata.type": "microsoft.graph.aadUserNotificationRecipient",
                    "userId": user,
                },
                "templateParameters": [{"name": "meeting", "value": subject}],
            },
        )
        response.raise_for_status()


class MeetingWatch:
    def __init__(self) -> None:
        self.installed: dict[str, float] = {}
        # Installed but the tab not pinned yet: whether the lecturer is still
        # owed the notice, and when it was first tried.
        self.unfinished: dict[str, tuple[bool, float]] = {}
        self.catalog: str | None = None
        self.task: asyncio.Task | None = None

    def start(self, settings: Settings) -> None:
        if settings.teams_auto_join_enabled and self.task is None:
            self.task = asyncio.create_task(self._run(), name="teams-meeting-watch")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def _run(self) -> None:
        while True:
            settings = get_settings()
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                    graph = Graph(client, await graph_token(client, settings))
                    await self.sweep(settings, graph)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad sweep must not stop the next
                log.warning("Teams meeting sweep failed: %s", type(exc).__name__)
            await asyncio.sleep(settings.teams_auto_join_interval_seconds)

    def _forget_old(self) -> None:
        now = time.monotonic()
        self.installed = {
            thread: at for thread, at in self.installed.items() if now - at < REMEMBER_SECONDS
        }
        self.unfinished = {
            thread: left
            for thread, left in self.unfinished.items()
            if now - left[1] < REMEMBER_SECONDS
        }

    async def sweep(
        self, settings: Settings, graph: Graph, now: datetime | None = None, factory=None
    ) -> int:
        """Put C.L.I.P in the coming meetings of every linked lecturer.
        Returns how many meetings it was installed into."""
        self._forget_old()
        if self.catalog is None:
            self.catalog = settings.teams_catalog_app_id or await graph.catalog_id(
                settings.teams_app_id
            )
            if self.catalog is None:
                log.warning("C.L.I.P is not in this organisation's Teams app catalog")
                return 0
        start = now or datetime.now(UTC)
        end = start + timedelta(days=settings.teams_auto_join_days)
        installed = 0
        async with (factory or get_session_factory())() as db:
            # Staff only: a student's calendar is never read.
            linked = (
                await db.execute(
                    select(TeamsUserMapping.teams_user_id, TeamsUserMapping.user_id)
                    .join(User, User.user_id == TeamsUserMapping.user_id)
                    .where(
                        func.lower(TeamsUserMapping.tenant_id) == settings.tenant_id.lower(),
                        User.role.in_(("lecturer", "admin")),
                    )
                )
            ).all()
            for teams_user, user_id in linked:
                principal = await session_lifecycle.act_as_lecturer(
                    db, user_id, "calendar", settings
                )
                if principal is None:
                    continue
                try:
                    codes = [course.code for course in await my_courses(db, principal)]
                    if not codes:
                        continue
                    events = await graph.calendar(teams_user, start - timedelta(hours=1), end)
                except (ClipError, httpx.HTTPError, ValueError) as exc:
                    await db.rollback()
                    log.warning("calendar of a lecturer not read: %s", type(exc).__name__)
                    continue
                for meeting in upcoming_meetings(events):
                    if await self._join(db, graph, settings, teams_user, meeting, codes):
                        installed += 1
        return installed

    async def _join(
        self,
        db,
        graph: Graph,
        settings: Settings,
        teams_user: str,
        meeting: Meeting,
        codes: list[str],
    ) -> bool:
        if meeting.thread in self.installed:
            return False
        assert self.catalog is not None
        left = self.unfinished.pop(meeting.thread, None)
        if left is None:
            known = await db.scalar(
                select(TeamsMeetingReference.meeting_id).where(
                    TeamsMeetingReference.meeting_id == meeting_id_for_thread(meeting.thread)
                )
            )
            if known is not None:
                # Added by hand, or by an earlier process.
                self.installed[meeting.thread] = time.monotonic()
                return False
            try:
                fresh = await graph.install(meeting.thread, self.catalog)
            except httpx.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                log.info(
                    "C.L.I.P not installed in a meeting yet (%s)", status or type(exc).__name__
                )
                return False
            first_tried = time.monotonic()
        else:
            # The install worked on an earlier sweep but the tab did not. The
            # bot has usually heard from the chat by now, so the reference
            # check above would wrongly call this meeting done.
            fresh, first_tried = left
        try:
            await graph.pin_tab(meeting.thread, self.catalog, settings.teams_app_base_url)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("the C.L.I.P tab was not pinned in a meeting: %s", type(exc).__name__)
            self.unfinished[meeting.thread] = (fresh, first_tried)
            return False
        self.installed[meeting.thread] = time.monotonic()
        if fresh:
            code = course_in_title(meeting.subject, codes)
            try:
                await graph.notify(
                    meeting.thread,
                    teams_user,
                    meeting.subject,
                    notice_text(meeting.subject, code),
                    tab_deep_link(settings.teams_app_id, meeting.thread),
                )
            except httpx.HTTPError as exc:
                log.warning("the lecturer was not told about a meeting: %s", type(exc).__name__)
        log.info("C.L.I.P is in a meeting a lecturer organises")
        return fresh


watch = MeetingWatch()
