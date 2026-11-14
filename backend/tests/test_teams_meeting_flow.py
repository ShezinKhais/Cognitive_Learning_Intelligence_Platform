"""The bot in a meeting with nothing linked, its cards, and people joining.

Owner: General CS, Phase 8. Teams is faked: the meeting details the bot
reads, and the cards it posts, never leave the test.
"""

from __future__ import annotations

import asyncio
import random
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.auth.store import LECTURER_ID, get_consent_repository
from app.core.config import get_settings
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.models.session import Session
from app.models.teams_meeting_reference import TeamsMeetingReference
from app.models.teams_roster_sync import TeamsRosterSync
from app.models.teams_user_mapping import TeamsUserMapping
from app.realtime.classroom import classroom
from app.schemas.identity import ConsentType
from app.schemas.meetings import TeamsActivity
from app.services import teams_meeting_flow as flow_module
from app.services import teams_replies
from app.services.meeting_directory import InMemoryMeetingDirectory, meetings
from app.services.meeting_organiser import thread_in
from app.services.teams_meeting_flow import (
    DISMISS,
    NOT_A_CLASS,
    START,
    answer_card,
    card_action,
    course_in_title,
    meeting_started_unlinked,
    participants_changed,
    question_card,
    started_card,
)
from app.services.teams_presence import MeetingPresence

SERVICE_URL = "https://smba.trafficmanager.net/emea/"
JOIN = "application/vnd.microsoft.meetingParticipantJoin"
LEAVE = "application/vnd.microsoft.meetingParticipantLeave"


# -- reading the title --------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "found"),
    [
        ("ZQ1234 Week 5 Lecture", "ZQ1234"),
        ("zq-1234 tutorial", "ZQ1234"),
        ("Week 5 catch-up", None),
        ("ZQ1234 and AB5678 joint review", None),
        (None, None),
    ],
)
def test_the_one_course_the_title_names_is_found(title, found) -> None:
    assert course_in_title(title, ["ZQ1234", "AB5678"]) == found


def test_a_course_the_organiser_does_not_teach_is_not_read_from_the_title() -> None:
    assert course_in_title("CS9999 Week 1", ["ZQ1234"]) is None


# -- the cards ---------------------------------------------------------------------


def test_the_started_card_offers_to_undo_it() -> None:
    session_id = uuid4()
    card = started_card("ZQ1234", "Week 5", session_id)
    [action] = card["actions"]
    assert action["title"] == "Not a class"
    assert action["data"] == {"clip": NOT_A_CLASS, "session": str(session_id)}


def test_the_question_card_lists_the_organisers_courses() -> None:
    card = question_card([("ZQ1234", "Algorithms"), ("AB5678", "Networks")])
    [choices] = [item for item in card["body"] if item["type"] == "Input.ChoiceSet"]
    assert [c["value"] for c in choices["choices"]] == ["ZQ1234", "AB5678"]
    assert [a["data"]["clip"] for a in card["actions"]] == [START, DISMISS]


def _message(value=None, text=None, **extra) -> TeamsActivity:  # noqa: ANN001, ANN003
    return TeamsActivity.model_validate(
        {
            "type": "message",
            "serviceUrl": SERVICE_URL,
            "channelId": "msteams",
            **({"value": value} if value is not None else {}),
            **({"text": text} if text is not None else {}),
            **extra,
        }
    )


def test_only_a_press_on_a_clip_card_is_a_card_action() -> None:
    assert card_action(_message({"clip": START, "course": "ZQ1234"})) is not None
    assert card_action(_message({"other": "card"})) is None
    assert card_action(_message(text="status")) is None


async def test_a_card_press_gets_no_help_reply() -> None:
    assert await teams_replies.reply_text(None, _message({"clip": DISMISS})) is None


# -- in a meeting ------------------------------------------------------------------


class _Teams:
    """The meeting as Teams reports it, and the cards the bot posts."""

    def __init__(self, organiser: str, title: str | None) -> None:
        self.organiser = organiser
        self.title = title
        self.posted: list[tuple[dict, str | None]] = []

    async def fetch(self, settings, service_url, meeting_id):  # noqa: ANN001, ANN201
        return {"organizer": {"aadObjectId": self.organiser}, "details": {"title": self.title}}

    async def post(self, settings, service_url, conversation_id, card, replace):  # noqa: ANN001, ANN201
        self.posted.append((card, replace))


@pytest.fixture
async def world(db, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    """A lecturer teaching one course, linked to their Teams account, and a
    meeting the bot is in."""
    monkeypatch.setattr(meetings, "directory", InMemoryMeetingDirectory())
    monkeypatch.setattr(flow_module, "flow", flow_module.MeetingFlow())
    welcomed: list[tuple] = []
    monkeypatch.setattr(
        flow_module.notifications, "enqueue_welcome", lambda *args: welcomed.append(args)
    )
    # A class started however it is tells the meeting through the classroom.
    monkeypatch.setattr(classroom, "class_started_notifier", lambda sid: welcomed.append((sid,)))
    monkeypatch.setattr(flow_module, "presence", MeetingPresence())
    emptied: list[str] = []

    async def end_empty(meeting_id: str) -> None:
        emptied.append(meeting_id)

    monkeypatch.setattr(flow_module, "end_empty_class", end_empty)
    _, factory, created = db
    tenant = f"tenant-{uuid4().hex}"
    organiser = uuid4().hex
    meeting = f"meeting-{uuid4().hex}"
    code = f"ZQ{random.randint(1000, 9999)}"
    # A development account: outside production they sign in from memory.
    lecturer = LECTURER_ID
    get_consent_repository(get_settings()).record(lecturer, ConsentType.TERMS, True)
    async with factory() as seed:
        course = Course(code=code, name="Algorithms")
        seed.add(course)
        await seed.flush()
        created["course"].append(course.id)
        seed.add(CourseLecturer(course_id=course.id, user_id=lecturer))
        seed.add(TeamsUserMapping(tenant_id=tenant, teams_user_id=organiser, user_id=lecturer))
        seed.add(
            TeamsMeetingReference(
                meeting_id=meeting,
                service_url=SERVICE_URL,
                conversation_id="chat-1",
                tenant_id=tenant,
            )
        )
        await seed.commit()
    settings = get_settings().model_copy(
        update={"teams_notifications_enabled": True, "tenant_id": tenant}
    )
    yield {
        "factory": factory,
        "settings": settings,
        "tenant": tenant,
        "organiser": organiser,
        "meeting": meeting,
        "code": code,
        "lecturer": lecturer,
        "welcomed": welcomed,
        "emptied": emptied,
    }
    async with factory() as cleanup:
        await cleanup.execute(delete(TeamsRosterSync).where(TeamsRosterSync.meeting_id == meeting))
        await cleanup.execute(
            delete(TeamsMeetingReference).where(TeamsMeetingReference.meeting_id == meeting)
        )
        await cleanup.execute(delete(TeamsUserMapping).where(TeamsUserMapping.tenant_id == tenant))
        await cleanup.commit()


def _started_event(meeting: str) -> TeamsActivity:
    return TeamsActivity.model_validate(
        {
            "type": "event",
            "name": "application/vnd.microsoft.meetingStart",
            "serviceUrl": SERVICE_URL,
            "channelId": "msteams",
            "conversation": {"id": "chat-1"},
            "channelData": {"meeting": {"id": meeting}},
        }
    )


def _press(meeting: str, by: str, value: dict) -> TeamsActivity:
    return _message(
        value,
        conversation={"id": "chat-1"},
        channelData={"meeting": {"id": meeting}},
        replyToId="card-1",
        **{"from": {"id": "29:someone", "aadObjectId": by}},
    )


async def _session(world) -> Session | None:  # noqa: ANN001
    session_id = await meetings.directory.session_for(world["meeting"])
    if session_id is None:
        return None
    async with world["factory"]() as look:
        return await look.get(Session, session_id)


async def _started_unlinked(world, teams: _Teams) -> None:  # noqa: ANN001
    async with world["factory"]() as db:
        await meeting_started_unlinked(
            db,
            _started_event(world["meeting"]),
            world["meeting"],
            world["settings"],
            fetch=teams.fetch,
            post=teams.post,
        )


async def _pressed(world, teams: _Teams, by: str, value: dict) -> None:  # noqa: ANN001
    async with world["factory"]() as db:
        await answer_card(
            db,
            _press(world["meeting"], by, value),
            world["settings"],
            fetch=teams.fetch,
            post=teams.post,
        )


async def test_a_meeting_titled_with_the_course_starts_its_class(world) -> None:
    teams = _Teams(world["organiser"], f"{world['code']} Week 5 Lecture")

    await _started_unlinked(world, teams)

    session = await _session(world)
    assert session is not None and session.status == "active"
    assert session.title == f"{world['code']} Week 5 Lecture"
    [(card, replace)] = teams.posted
    assert replace is None
    assert card["actions"][0]["data"] == {"clip": NOT_A_CLASS, "session": str(session.session_id)}
    assert world["welcomed"] == [(session.session_id,)]


async def test_a_start_delivered_twice_posts_one_card(world) -> None:
    teams = _Teams(world["organiser"], f"{world['code']} Week 5")
    await _started_unlinked(world, teams)
    await _started_unlinked(world, teams)
    assert len(teams.posted) == 1


async def test_a_title_without_a_course_asks_whether_this_is_a_class(world) -> None:
    teams = _Teams(world["organiser"], "Weekly catch-up")

    await _started_unlinked(world, teams)

    assert await _session(world) is None
    [(card, _)] = teams.posted
    [choices] = [item for item in card["body"] if item["type"] == "Input.ChoiceSet"]
    # Every course the organiser teaches, theirs from other tests included.
    assert world["code"] in [c["value"] for c in choices["choices"]]


async def test_an_organiser_without_a_clip_account_is_left_alone(world) -> None:
    teams = _Teams(uuid4().hex, f"{world['code']} Week 5")
    await _started_unlinked(world, teams)
    assert teams.posted == [] and await _session(world) is None


async def test_only_the_organisers_press_starts_the_class(world) -> None:
    teams = _Teams(world["organiser"], "Weekly catch-up")
    start = {"clip": START, "course": world["code"]}

    await _pressed(world, teams, uuid4().hex, start)
    assert teams.posted == [] and await _session(world) is None

    await _pressed(world, teams, world["organiser"].upper(), start)
    session = await _session(world)
    assert session is not None and session.status == "active"
    [(card, replace)] = teams.posted
    assert replace == "card-1"
    assert "has started" in card["body"][1]["text"]


async def test_a_course_the_organiser_does_not_teach_is_not_started(world) -> None:
    teams = _Teams(world["organiser"], "Weekly catch-up")
    await _pressed(world, teams, world["organiser"], {"clip": START, "course": "CS9999"})
    assert teams.posted == [] and await _session(world) is None


async def test_not_a_class_ends_the_class_the_bot_started(world) -> None:
    teams = _Teams(world["organiser"], f"{world['code']} Week 5")
    await _started_unlinked(world, teams)
    session = await _session(world)

    await _pressed(
        world,
        teams,
        world["organiser"],
        {"clip": NOT_A_CLASS, "session": str(session.session_id)},
    )

    assert (await _session(world)).status == "ended"
    assert teams.posted[-1][1] == "card-1"


async def test_not_a_class_names_the_session_it_ends(world) -> None:
    teams = _Teams(world["organiser"], f"{world['code']} Week 5")
    await _started_unlinked(world, teams)
    await _pressed(world, teams, world["organiser"], {"clip": NOT_A_CLASS, "session": str(uuid4())})
    assert (await _session(world)).status == "active"


def _joined(
    meeting: str, event_id: str, *members: tuple[str, str], name: str = JOIN
) -> TeamsActivity:
    return TeamsActivity.model_validate(
        {
            "type": "event",
            "name": name,
            "id": event_id,
            "serviceUrl": SERVICE_URL,
            "channelId": "msteams",
            "channelData": {"meeting": {"id": meeting}},
            "value": {
                "members": [
                    {"user": {"id": teams_id, "aadObjectId": aad}, "meeting": {"inMeeting": True}}
                    for teams_id, aad in members
                ]
            },
        }
    )


async def test_someone_joining_a_running_class_gets_clip_and_the_join_is_kept(world) -> None:
    teams = _Teams(world["organiser"], f"{world['code']} Week 5")
    await _started_unlinked(world, teams)
    session = await _session(world)
    world["welcomed"].clear()
    joined = _joined(world["meeting"], "event-1", ("29:student", "AAD-Student"), ("8:guest", "x"))

    async with world["factory"]() as db:
        await participants_changed(db, joined, world["settings"])
        # Teams may deliver it again: still one roster event.
        await participants_changed(db, joined, world["settings"])

    assert world["welcomed"][0] == (session.session_id, {"aad-student": "29:student"})
    async with world["factory"]() as look:
        syncs = (
            await look.scalars(
                select(TeamsRosterSync).where(TeamsRosterSync.meeting_id == world["meeting"])
            )
        ).all()
    assert [(s.event_type, s.participant_count) for s in syncs] == [("participant_joined", 1)]


async def test_joining_a_meeting_with_no_class_does_nothing(world) -> None:
    async with world["factory"]() as db:
        await participants_changed(
            db, _joined(world["meeting"], "event-2", ("29:s", "aad-s")), world["settings"]
        )
    assert world["welcomed"] == []


# -- everyone leaving -------------------------------------------------------------


async def _in_call(world, event_id: str, *members: tuple[str, str], name: str = JOIN) -> None:  # noqa: ANN001
    async with world["factory"]() as db:
        await participants_changed(
            db, _joined(world["meeting"], event_id, *members, name=name), world["settings"]
        )


async def test_the_class_ends_once_everyone_has_left_the_call(world) -> None:
    settings = world["settings"].model_copy(update={"teams_empty_meeting_end_seconds": 0.01})
    world["settings"] = settings
    await _started_unlinked(world, _Teams(world["organiser"], f"{world['code']} Week 5"))
    await _in_call(world, "j1", ("29:a", "aad-a"), ("29:b", "aad-b"))
    await _in_call(world, "l1", ("29:a", "aad-a"), name=LEAVE)
    await asyncio.sleep(0.05)
    assert world["emptied"] == []

    await _in_call(world, "l2", ("29:b", "aad-b"), name=LEAVE)
    await asyncio.sleep(0.05)
    assert world["emptied"] == [world["meeting"]]


async def test_someone_rejoining_in_the_wait_keeps_the_class_running(world) -> None:
    settings = world["settings"].model_copy(update={"teams_empty_meeting_end_seconds": 1.0})
    world["settings"] = settings
    await _started_unlinked(world, _Teams(world["organiser"], f"{world['code']} Week 5"))
    await _in_call(world, "j1", ("29:a", "aad-a"))
    await _in_call(world, "l1", ("29:a", "aad-a"), name=LEAVE)
    await _in_call(world, "j2", ("29:a", "aad-a"))
    await asyncio.sleep(1.3)
    assert world["emptied"] == []


async def test_a_leave_from_someone_never_seen_joining_ends_nothing(world) -> None:
    settings = world["settings"].model_copy(update={"teams_empty_meeting_end_seconds": 0.01})
    world["settings"] = settings
    await _started_unlinked(world, _Teams(world["organiser"], f"{world['code']} Week 5"))
    await _in_call(world, "l1", ("29:a", "aad-a"), name=LEAVE)
    await asyncio.sleep(0.05)
    assert world["emptied"] == []


async def test_a_wait_of_zero_never_ends_the_class() -> None:
    presence = MeetingPresence()
    ended: list[str] = []

    async def end(meeting_id: str) -> None:
        ended.append(meeting_id)

    presence.joined("m", {"a"})
    assert presence.left("m", {"a"}) is True
    presence.end_when_empty("m", 0, end)
    await asyncio.sleep(0.01)
    assert ended == [] and presence.timers == {}


# -- linking from the website -------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_NjA1YzQ0ZjMt%40thread.v2/0"
        "?context=%7b%22Tid%22%3a%22x%22%7d",
        "https://teams.microsoft.com/l/meetup-join/19:meeting_NjA1YzQ0ZjMt@thread.v2/0",
        "https://teams.microsoft.com/l/meetup-join/19%253ameeting_NjA1YzQ0ZjMt%2540thread.v2/0",
    ],
)
def test_a_join_link_names_its_meeting_chat(link: str) -> None:
    assert thread_in(link) == "19:meeting_NjA1YzQ0ZjMt@thread.v2"


def test_a_link_that_is_not_a_teams_meeting_names_nothing() -> None:
    assert thread_in("https://example.com/meet/abc") is None
    assert thread_in("https://teams.microsoft.com/l/channel/19%3aabc%40thread.tacv2") is None
