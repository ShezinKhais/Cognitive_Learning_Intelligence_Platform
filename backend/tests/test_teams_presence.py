"""Ending a class after its Teams call empties: a rejoin or Keep running that
arrives while the end is looking things up still stops it, and only the class
the wait was started for is ended. While breakout rooms are open the end is
held, and starts again once they close."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.services import teams_presence
from app.services.teams_presence import EVERYONE_LEFT, LECTURER_LEFT, MeetingPresence, end_class

MEETING = "meeting-1"


class _Db:
    async def __aenter__(self) -> _Db:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def scalar(self, _query: object) -> str:
        return "active"


class _Directory:
    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def session_for(self, _meeting_id: str) -> UUID:
        self.reached.set()
        await self.release.wait()
        return self.session_id

    async def meetings_for(self, session_ids: list[UUID]) -> dict[UUID, str]:
        return {sid: MEETING for sid in session_ids if sid == self.session_id}


@pytest.fixture
def ending(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    session_id = uuid4()
    presence = MeetingPresence()
    directory = _Directory(session_id)
    owner_reached, owner_release = asyncio.Event(), asyncio.Event()
    owner_release.set()
    ended: list[UUID] = []
    rooms = {"open": False}
    settings = teams_presence.get_settings().model_copy(
        update={"teams_empty_meeting_end_seconds": 0.01}
    )

    async def meeting_owner(*_args: object) -> object:
        owner_reached.set()
        await owner_release.wait()
        return object()

    lock_reached, lock_release = asyncio.Event(), asyncio.Event()
    lock_release.set()

    async def end_session(_db: object, _owner: object, sid: UUID, still_wanted=None) -> None:  # noqa: ANN001
        # The real one waits for the session row lock, then asks still_wanted.
        lock_reached.set()
        await lock_release.wait()
        if still_wanted is not None and not still_wanted():
            raise teams_presence.session_lifecycle.EndCalledOff("called off")
        ended.append(sid)

    monkeypatch.setattr(teams_presence, "presence", presence)
    monkeypatch.setattr(teams_presence.meetings, "directory", directory)
    monkeypatch.setattr(teams_presence, "get_session_factory", lambda: _Db)
    monkeypatch.setattr(teams_presence.classroom, "anyone_connected", lambda _sid: False)
    monkeypatch.setattr(teams_presence.classroom, "rooms_open", lambda _sid: rooms["open"])
    monkeypatch.setattr(teams_presence, "get_settings", lambda: settings)
    monkeypatch.setattr(teams_presence.session_lifecycle, "meeting_owner", meeting_owner)
    monkeypatch.setattr(teams_presence.session_lifecycle, "end_session", end_session)
    return {
        "session_id": session_id,
        "presence": presence,
        "directory": directory,
        "owner_reached": owner_reached,
        "owner_release": owner_release,
        "ended": ended,
        "lock_reached": lock_reached,
        "lock_release": lock_release,
        "rooms": rooms,
    }


def _start(ending, reason: str = EVERYONE_LEFT, waiting_for=None):  # noqa: ANN001, ANN202
    presence: MeetingPresence = ending["presence"]
    presence.joined(MEETING, {"lecturer", "student"})
    presence.left(MEETING, {"lecturer", "student"})
    wait = presence.end_after(
        MEETING, ending["session_id"], reason, 0.01, end_class, waiting_for=waiting_for
    )
    assert wait is not None and wait.task is not None
    return wait


async def test_an_uncancelled_wait_ends_its_class(ending) -> None:  # noqa: ANN001
    wait = _start(ending)
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == [ending["session_id"]]
    assert ending["presence"].waits == {}


async def test_a_rejoin_during_the_lookup_stops_the_end(ending) -> None:  # noqa: ANN001
    ending["directory"].release.clear()
    wait = _start(ending)
    await asyncio.wait_for(ending["directory"].reached.wait(), 2)
    assert ending["presence"].joined(MEETING, {"student"}) is wait
    ending["directory"].release.set()
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == []
    assert ending["presence"].waits == {}


async def test_keep_running_during_the_owner_lookup_stops_the_end(ending) -> None:  # noqa: ANN001
    ending["owner_release"].clear()
    wait = _start(ending, LECTURER_LEFT, waiting_for={"lecturer"})
    await asyncio.wait_for(ending["owner_reached"].wait(), 2)
    # What keep_running does once it has found the wait.
    assert ending["presence"].cancel(MEETING) is wait
    ending["owner_release"].set()
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == []


async def test_a_rejoin_while_waiting_for_the_row_lock_stops_the_end(ending) -> None:  # noqa: ANN001
    ending["lock_release"].clear()
    wait = _start(ending)
    await asyncio.wait_for(ending["lock_reached"].wait(), 2)
    assert ending["presence"].joined(MEETING, {"student"}) is wait
    ending["lock_release"].set()
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == []


async def test_a_meeting_relinked_to_another_class_is_not_ended(ending) -> None:  # noqa: ANN001
    wait = _start(ending)
    ending["directory"].session_id = uuid4()
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == []


async def test_a_new_wait_during_the_end_is_left_in_place(ending) -> None:  # noqa: ANN001
    ending["directory"].release.clear()
    wait = _start(ending)
    await asyncio.wait_for(ending["directory"].reached.wait(), 2)
    newer = ending["presence"].end_after(
        MEETING, ending["session_id"], EVERYONE_LEFT, 60, end_class
    )
    ending["directory"].release.set()
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == []
    assert ending["presence"].waits == {MEETING: newer}
    ending["presence"].cancel(MEETING)


async def test_rooms_opened_in_the_wait_hold_the_end_until_they_close(ending) -> None:  # noqa: ANN001
    wait = _start(ending)
    ending["rooms"]["open"] = True
    await asyncio.wait_for(wait.task, 2)
    assert ending["ended"] == []
    assert MEETING in ending["presence"].held and ending["presence"].waits == {}

    ending["rooms"]["open"] = False
    again = await teams_presence.rooms_closed(ending["session_id"])
    assert again is not None and MEETING not in ending["presence"].held
    await asyncio.wait_for(again.task, 2)
    assert ending["ended"] == [ending["session_id"]]


async def test_a_rejoin_while_held_drops_the_hold(ending) -> None:  # noqa: ANN001
    presence: MeetingPresence = ending["presence"]
    presence.hold(MEETING, ending["session_id"], EVERYONE_LEFT)
    presence.joined(MEETING, {"student"})
    assert presence.held == {}
    assert await teams_presence.rooms_closed(ending["session_id"]) is None
    assert ending["ended"] == []


async def test_a_held_lecturer_wait_waits_for_the_lecturer_only(ending) -> None:  # noqa: ANN001
    presence: MeetingPresence = ending["presence"]
    presence.hold(MEETING, ending["session_id"], LECTURER_LEFT, waiting_for={"lecturer"})
    presence.joined(MEETING, {"student"})
    assert MEETING in presence.held
    presence.joined(MEETING, {"lecturer"})
    assert presence.held == {}
