"""Breakout rooms the lecturer assigns: the plan, and what each student is told.

Owner: General CS, Phase 6.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.errors import ValidationError
from app.schemas.breakout import RoomPlanIn, RoomPlanRoomIn
from app.schemas.events import ServerEventType
from app.schemas.identity import Role
from app.schemas.session import SessionStatus
from app.services.breakout import validate_plan

from .classroom_support import join_as, make_room, make_row

pytestmark = pytest.mark.usefixtures("fake_session_repository")


def _plan(*rooms: tuple[str, list]) -> RoomPlanIn:
    return RoomPlanIn(rooms=[RoomPlanRoomIn(label=label, user_ids=ids) for label, ids in rooms])


def test_a_plan_places_course_students_once_each() -> None:
    a, b = uuid4(), uuid4()
    students = {a: "Ada", b: "Ben"}
    assert validate_plan(_plan(("Room 1", [a]), (" Room  2 ", [b])), students, 10) == {
        a: "Room 1",
        b: "Room 2",
    }


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        (RoomPlanIn(), "at least one"),
        (None, "not on this course"),
        ("twice", "more than one room"),
        ("same-name", "Two rooms"),
        ("blank", "needs a name"),
        ("too-many", "at most 1"),
    ],
)
def test_a_plan_that_cannot_be_used_says_why(plan, message) -> None:
    a = uuid4()
    students = {a: "Ada"}
    limit = 10
    if plan is None:
        plan = _plan(("Room 1", [uuid4()]))
    elif plan == "twice":
        plan = _plan(("Room 1", [a]), ("Room 2", [a]))
    elif plan == "same-name":
        plan = _plan(("Room 1", []), ("room 1", []))
    elif plan == "blank":
        plan = _plan(("​\x01", []))
    elif plan == "too-many":
        plan, limit = _plan(("Room 1", []), ("Room 2", [])), 1
    with pytest.raises(ValidationError, match=message):
        validate_plan(plan, students, limit)


async def _class():
    room, events = make_room()
    row = make_row()
    room.activate(row.session_id)
    return room, events, row


async def test_each_student_is_told_their_room_and_staff_see_the_rooms() -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    ada_socket, ada = await join_as(events, row.session_id, Role.STUDENT)
    ben_socket, ben = await join_as(events, row.session_id, Role.STUDENT)

    assert await room.assign_rooms(row.session_id, {ada: "Room 1", ben: "Room 2"})

    assert [e["data"] for e in ada_socket.of(ServerEventType.ROOM_ASSIGNED)] == [
        {"room_label": "Room 1"}
    ]
    assert [e["data"] for e in ben_socket.of(ServerEventType.ROOM_ASSIGNED)] == [
        {"room_label": "Room 2"}
    ]
    assert {e["data"]["room_label"] for e in lecturer.of(ServerEventType.ROOM_STATUS)} == {
        "Room 1",
        "Room 2",
    }
    assert room.room_plan(row.session_id) == {ada: "Room 1", ben: "Room 2"}
    await room.shutdown()


async def test_a_new_plan_tells_a_student_left_out_that_they_have_no_room() -> None:
    room, events, row = await _class()
    ada_socket, ada = await join_as(events, row.session_id, Role.STUDENT)
    _, ben = await join_as(events, row.session_id, Role.STUDENT)
    await room.assign_rooms(row.session_id, {ada: "Room 1", ben: "Room 1"})

    await room.assign_rooms(row.session_id, {ben: "Room 2"})

    assert [e["data"] for e in ada_socket.of(ServerEventType.ROOM_ASSIGNED)] == [
        {"room_label": "Room 1"},
        {"room_label": None},
    ]
    assert room.room_plan(row.session_id) == {ben: "Room 2"}
    await room.shutdown()


async def test_closing_brings_everyone_back_including_self_named_rooms() -> None:
    room, events, row = await _class()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    ada_socket, ada = await join_as(events, row.session_id, Role.STUDENT)
    await room.assign_rooms(row.session_id, {ada: "Room 1"})

    assert await room.close_rooms(row.session_id)

    assert ada_socket.of(ServerEventType.ROOM_ASSIGNED)[-1]["data"] == {"room_label": None}
    assert room.room_plan(row.session_id) == {}
    assert room.rooms(row.session_id) == []
    last = lecturer.of(ServerEventType.ROOM_STATUS)[-1]["data"]
    assert last["room_label"] == "Room 1" and last["members"] == 0
    await room.shutdown()


async def test_a_class_that_is_not_running_cannot_be_split() -> None:
    room, _, _ = await _class()
    assert not await room.assign_rooms(uuid4(), {uuid4(): "Room 1"})
    assert not await room.close_rooms(uuid4())
    assert room.room_plan(uuid4()) is None
    await room.shutdown()


async def test_a_reopened_panel_is_told_its_room_again() -> None:
    room, events, row = await _class()
    _, ada = await join_as(events, row.session_id, Role.STUDENT)
    await room.assign_rooms(row.session_id, {ada: "Room 3"})

    welcome = room.welcome(row.session_id, SessionStatus.ACTIVE, ada, Role.STUDENT)

    assert (ServerEventType.ROOM_ASSIGNED, {"room_label": "Room 3"}) in welcome
    await room.shutdown()
