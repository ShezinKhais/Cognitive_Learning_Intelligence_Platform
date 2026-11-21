"""C.L.I.P put into lecturers' Teams meetings by the calendar sweep.

Owner: General CS, Phase 8. Microsoft Graph is faked; nothing leaves the test.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from app.auth.store import LECTURER_ID, STUDENT_ID, get_consent_repository
from app.core.config import Settings, get_settings
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.teams_user_mapping import TeamsUserMapping
from app.schemas.identity import ConsentType
from app.schemas.meetings import meeting_id_for_thread
from app.services.teams_meeting_watch import (
    MeetingWatch,
    notice_text,
    tab_deep_link,
    upcoming_meetings,
)

APP_ID = "00000000-0000-0000-0000-000000000051"


def _event(thread: str | None, subject: str = "Weekly catch-up", **changes) -> dict:  # noqa: ANN003
    join = (
        f"https://teams.microsoft.com/l/meetup-join/{thread.replace(':', '%3a')}/0"
        if thread
        else None
    )
    return {
        "subject": subject,
        "isOnlineMeeting": True,
        "isOrganizer": True,
        "isCancelled": False,
        "onlineMeeting": {"joinUrl": join} if join else None,
        **changes,
    }


def _thread() -> str:
    return f"19:meeting_{uuid4().hex}@thread.v2"


def test_only_teams_meetings_the_lecturer_organises_are_kept_once_each() -> None:
    mine, recurring = _thread(), _thread()
    events = [
        _event(mine, "ZQ1234 Week 5"),
        _event(recurring),
        _event(recurring),
        _event(_thread(), isOrganizer=False),
        _event(_thread(), isCancelled=True),
        _event(_thread(), isOnlineMeeting=False),
        _event(None),
        "not an event",
    ]
    found = upcoming_meetings(events)
    assert [m.thread for m in found] == [mine, recurring]
    assert found[0].subject == "ZQ1234 Week 5"
    assert upcoming_meetings(None) == []


def test_the_notice_opens_the_clip_tab_in_that_meeting() -> None:
    thread = _thread()
    link = tab_deep_link(APP_ID, thread)
    parts = urlsplit(link)
    assert parts.netloc == "teams.microsoft.com"
    assert parts.path == f"/l/entity/{APP_ID}/clip.meeting"
    context = json.loads(parse_qs(parts.query)["context"][0])
    assert context == {"chatId": thread, "contextType": "chat"}


def test_the_notice_says_which_class_or_asks() -> None:
    assert "runs as a ZQ1234 class" in notice_text("ZQ1234 Week 5", "ZQ1234")
    assert "Is it a class?" in notice_text("Catch-up", None)


def test_auto_join_needs_teams_notifications() -> None:
    with pytest.raises(ValueError, match="TEAMS_NOTIFICATIONS_ENABLED"):
        Settings(teams_auto_join_enabled=True)


class _Graph:
    """Microsoft Graph as the sweep sees it."""

    def __init__(self, events: dict[str, list], chat_ready: bool = True) -> None:
        self.events = events
        self.chat_ready = chat_ready
        self.installed: list[str] = []
        self.tabs: list[str] = []
        self.notices: list[tuple[str, str, str]] = []
        self.calendars: list[str] = []

    async def calendar(self, user, start, end):  # noqa: ANN001, ANN201
        self.calendars.append(user)
        return self.events.get(user, [])

    async def catalog_id(self, external_id):  # noqa: ANN001, ANN201
        return "catalog-1"

    async def install(self, thread, catalog):  # noqa: ANN001, ANN201
        if not self.chat_ready:
            request = httpx.Request("POST", "https://graph.example/chats")
            raise httpx.HTTPStatusError(
                "not yet", request=request, response=httpx.Response(404, request=request)
            )
        fresh = thread not in self.installed
        self.installed.append(thread)
        return fresh

    async def pin_tab(self, thread, catalog, base):  # noqa: ANN001, ANN201
        self.tabs.append(thread)

    async def notify(self, thread, user, subject, text, link):  # noqa: ANN001, ANN201
        self.notices.append((thread, user, text))


@pytest.fixture
async def lecturer(db):  # noqa: ANN001, ANN201
    """A lecturer teaching one course and a student, both linked to Teams."""
    _, factory, created = db
    tenant = f"tenant-{uuid4().hex}"
    aad, student_aad = uuid4().hex, uuid4().hex
    code = f"ZQ{random.randint(1000, 9999)}"
    get_consent_repository(get_settings()).record(LECTURER_ID, ConsentType.TERMS, True)
    async with factory() as seed:
        course = Course(code=code, name="Algorithms")
        seed.add(course)
        await seed.flush()
        created["course"].append(course.id)
        seed.add(CourseLecturer(course_id=course.id, user_id=LECTURER_ID))
        seed.add(TeamsUserMapping(tenant_id=tenant, teams_user_id=aad, user_id=LECTURER_ID))
        seed.add(TeamsUserMapping(tenant_id=tenant, teams_user_id=student_aad, user_id=STUDENT_ID))
        await seed.commit()
    settings = get_settings().model_copy(
        update={
            "tenant_id": tenant,
            "teams_app_id": APP_ID,
            "teams_app_base_url": "https://clip.example",
        }
    )
    yield {
        "factory": factory,
        "settings": settings,
        "aad": aad,
        "student": student_aad,
        "code": code,
    }
    async with factory() as cleanup:
        await cleanup.execute(delete(TeamsUserMapping).where(TeamsUserMapping.tenant_id == tenant))
        await cleanup.execute(
            delete(TeamsMeetingReference).where(TeamsMeetingReference.tenant_id == tenant)
        )
        await cleanup.commit()


async def test_clip_joins_the_lecturers_meetings_and_tells_them_once(lecturer) -> None:
    named, other = _thread(), _thread()
    graph = _Graph({lecturer["aad"]: [_event(named, f"{lecturer['code']} Week 5"), _event(other)]})
    watch = MeetingWatch()

    assert (
        await watch.sweep(lecturer["settings"], graph, datetime.now(UTC), lecturer["factory"]) == 2
    )
    assert graph.installed == [named, other]
    assert graph.tabs == [named, other]
    texts = {thread: text for thread, _, text in graph.notices}
    assert f"runs as a {lecturer['code']} class" in texts[named]
    assert "Is it a class?" in texts[other]
    assert {user for _, user, _ in graph.notices} == {lecturer["aad"]}
    # A student's calendar is never read.
    assert lecturer["student"] not in graph.calendars

    # The next sweep leaves them alone.
    assert (
        await watch.sweep(lecturer["settings"], graph, datetime.now(UTC), lecturer["factory"]) == 0
    )
    assert len(graph.installed) == 2 and len(graph.notices) == 2


async def test_a_meeting_clip_is_already_in_is_left_alone(lecturer) -> None:
    thread = _thread()
    async with lecturer["factory"]() as seed:
        seed.add(
            TeamsMeetingReference(
                meeting_id=meeting_id_for_thread(thread),
                service_url="https://smba.trafficmanager.net/emea/",
                conversation_id=thread,
                tenant_id=lecturer["settings"].tenant_id,
            )
        )
        await seed.commit()
    graph = _Graph({lecturer["aad"]: [_event(thread)]})
    assert await MeetingWatch().sweep(lecturer["settings"], graph, None, lecturer["factory"]) == 0
    assert graph.installed == [] and graph.notices == []


async def test_a_chat_teams_has_not_made_yet_is_tried_again(lecturer) -> None:
    thread = _thread()
    graph = _Graph({lecturer["aad"]: [_event(thread)]}, chat_ready=False)
    watch = MeetingWatch()
    assert await watch.sweep(lecturer["settings"], graph, None, lecturer["factory"]) == 0
    graph.chat_ready = True
    assert await watch.sweep(lecturer["settings"], graph, None, lecturer["factory"]) == 1
    assert graph.installed == [thread]


async def test_an_install_already_there_is_not_announced_again(lecturer) -> None:
    thread = _thread()
    graph = _Graph({lecturer["aad"]: [_event(thread)]})
    graph.installed.append(thread)
    assert await MeetingWatch().sweep(lecturer["settings"], graph, None, lecturer["factory"]) == 0
    assert graph.notices == []
    assert graph.tabs == [thread]
