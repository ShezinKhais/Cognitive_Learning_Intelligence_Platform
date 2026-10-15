"""Best-effort checkpoint announcements through the public-cloud Teams connector.

Only authenticated Teams meeting events may establish an outbound reference.
The bounded background tasks never hold the classroom's question lock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select, update

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.session import Session
from app.models.student import Student
from app.models.teams_meeting_link import TeamsMeetingLink
from app.models.teams_user_mapping import TeamsUserMapping
from app.models.user import User
from app.schemas.meetings import TeamsActivity

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


def panel_url(base: str, session_id: UUID) -> str:
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
    return f"{parsed.scheme}://{parsed.netloc}/teams/meeting?{query}"


def checkpoint_card(target: str, course: str, title: str) -> dict:
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
                "text": "Open the student panel to respond to the current checkpoint.",
                "wrap": True,
            },
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "Open C.L.I.P", "url": target}],
    }


def meeting_deep_link(settings: Settings, conversation_id: str, target: str) -> str:
    query = urlencode(
        {
            "webUrl": target,
            "label": "C.L.I.P",
            "context": json.dumps(
                {
                    "chatId": conversation_id,
                    "contextType": "chat",
                }
            ),
        }
    )
    return f"https://teams.microsoft.com/l/entity/{settings.teams_app_id}/clip.meeting?{query}"


async def remember_reference(db, activity: TeamsActivity, settings: Settings) -> None:
    """Called only after BotAuthenticator.verify AND authorize succeeded."""
    if not settings.teams_notifications_enabled:
        return
    data = activity.channel_data or {}
    meeting = data.get("meeting") or {}
    tenant = data.get("tenant") or {}
    conversation = (activity.model_extra or {}).get("conversation") or {}
    meeting_id = meeting.get("id") if isinstance(meeting, dict) else None
    conversation_id = conversation.get("id") if isinstance(conversation, dict) else None
    tenant_id = tenant.get("id") if isinstance(tenant, dict) else None
    if (
        not isinstance(meeting_id, str)
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
    await db.execute(
        update(TeamsMeetingLink)
        .where(TeamsMeetingLink.meeting_id == meeting_id)
        .values(
            bot_service_url=service,
            bot_conversation_id=conversation_id,
            bot_tenant_id=tenant_id,
        )
    )
    await db.commit()


@dataclass(frozen=True)
class CheckpointNotice:
    session_id: UUID
    closes_at: float
    question_id: UUID


class TeamsNotifications:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()
        self.slots = asyncio.Semaphore(2)
        self.token_lock = asyncio.Lock()
        self.token = ""
        self.token_until = 0.0
        self.token_identity: tuple[str, str, str] | None = None

    def enqueue(self, session_id: UUID, question_id: UUID, closes_at: float) -> None:
        settings = get_settings()
        if not settings.teams_notifications_enabled:
            return
        if len(self.tasks) >= 100:
            log.warning("Teams notification skipped: queue full")
            return
        task = asyncio.create_task(self._run(CheckpointNotice(session_id, closes_at, question_id)))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def shutdown(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, notice: CheckpointNotice) -> None:
        try:
            async with self.slots:
                remaining = notice.closes_at - time.time()
                if remaining <= 0:
                    return
                async with asyncio.timeout(min(remaining, 12)):
                    await self.send(notice, get_settings())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                self.token_until = 0
            log.warning("Teams checkpoint notification refused: HTTP %s", exc.response.status_code)
        except Exception:
            # Neither credentials nor connector response bodies belong in logs.
            log.warning(
                "Teams checkpoint notification failed; WebSocket delivery remains available"
            )

    async def access_token(self, client: httpx.AsyncClient, settings: Settings) -> str:
        async with self.token_lock:
            identity = (settings.client_id, settings.tenant_id, settings.client_secret)
            if identity == self.token_identity and time.monotonic() < self.token_until:
                return self.token
            tenant = quote(settings.tenant_id, safe="")
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
        target = panel_url(settings.teams_app_base_url, notice.session_id)
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(TeamsMeetingLink, Session, Course)
                    .join(Session, Session.session_id == TeamsMeetingLink.session_id)
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
            link, session, course = row
            if (
                not link.bot_service_url
                or not link.bot_conversation_id
                or link.bot_tenant_id != settings.tenant_id
            ):
                return
            base = connector_url(link.bot_service_url)
            students = set(
                (
                    await db.scalars(
                        select(TeamsUserMapping.teams_user_id)
                        .join(User, User.user_id == TeamsUserMapping.user_id)
                        .join(Student, Student.user_id == User.user_id)
                        .where(
                            TeamsUserMapping.tenant_id == settings.tenant_id,
                            Student.course_id == session.course_id,
                            User.role == "student",
                            User.active.is_(True),
                        )
                    )
                ).all()
            )
            title, code = session.title, course.code
            meeting_id, conversation_id = link.meeting_id, link.bot_conversation_id
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
            token = await self.access_token(client, settings)
            headers = {"Authorization": f"Bearer {token}"}
            # Resolve Entra IDs to Teams 29: IDs using the authenticated meeting's roster.
            recipients: set[str] = set()
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
                    if (
                        member.get("aadObjectId") in students
                        and isinstance(user_id, str)
                        and user_id.startswith("29:")
                    ):
                        recipients.add(user_id)
                continuation = body.get("continuationToken")
                if not continuation:
                    break
            if not recipients or time.time() >= notice.closes_at:
                return
            response = await client.post(
                base + f"v3/conversations/{quote(conversation_id, safe='')}/activities",
                headers=headers,
                json={
                    "type": "message",
                    "text": "New checkpoint: open C.L.I.P to answer",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": checkpoint_card(
                                meeting_deep_link(settings, conversation_id, target),
                                code,
                                title,
                            ),
                        }
                    ],
                },
            )
            response.raise_for_status()
            ordered = sorted(recipients)
            for offset in range(0, len(ordered), 50):
                if time.time() >= notice.closes_at:
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
                                            "height": "300",
                                            "width": "400",
                                            "title": "New C.L.I.P checkpoint",
                                            "url": target,
                                        }
                                    },
                                }
                            ],
                        },
                    },
                )
                response.raise_for_status()
                if response.status_code == 207:
                    log.warning("Teams checkpoint notification partially delivered")


notifications = TeamsNotifications()
