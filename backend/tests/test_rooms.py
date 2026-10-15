"""Breakout rooms: which room each student is in, and how each is doing.

Owner: General CS, Phase 6.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.realtime.rooms import Refusal, RoomLimits, Rooms, room_key, shown_label
from app.schemas.events import MAX_ROOM_LABEL_LENGTH, RoomStatus

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
FRESH = timedelta(seconds=20)
MAX_ROOMS = 50


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _limits(fresh: timedelta = FRESH, max_rooms: int = MAX_ROOMS) -> RoomLimits:
    return RoomLimits(
        fresh=fresh,
        quiet_after=timedelta(seconds=60),
        needs_attention_after=timedelta(seconds=180),
        max_rooms=max_rooms,
    )


def _students(count: int) -> list[UUID]:
    return [uuid4() for _ in range(count)]


def _rooms(fresh: timedelta = FRESH, max_rooms: int = MAX_ROOMS) -> Rooms:
    return Rooms(_limits(fresh, max_rooms))


def _only(rooms: Rooms, now: datetime, connected: set[UUID]):  # noqa: ANN202
    [status] = rooms.statuses(now, connected)
    return status


# -- labels -------------------------------------------------------------------------


def test_labels_differing_in_case_and_whitespace_are_one_room_shown_as_first_spelt() -> None:
    rooms = _rooms()
    first, second = _students(2)

    assert rooms.confirm(first, "Room 1") is None
    assert rooms.confirm(second, "  room   1 ") is None

    status = _only(rooms, T0, {first, second})
    assert (status.room_label, status.members) == ("Room 1", 2)
    assert rooms.room_of(second) == "Room 1"


def test_characters_that_are_not_printed_are_cleaned_from_a_label() -> None:
    rooms = _rooms()
    first, second = _students(2)

    assert shown_label("Room\x00\t1\x07") == "Room 1"
    assert room_key(" ROOM  1 ") == room_key("room 1")
    # Cleaned before it is matched, so the stray characters do not make a second room.
    rooms.confirm(first, "Room\x00\t1\x07")
    rooms.confirm(second, "room 1")
    assert [s.room_label for s in rooms.statuses(T0, {first, second})] == ["Room 1"]


def test_a_label_is_shown_no_longer_than_the_most_the_contract_allows() -> None:
    assert len(shown_label("x" * (MAX_ROOM_LABEL_LENGTH + 50))) == MAX_ROOM_LABEL_LENGTH


def test_a_blank_label_is_refused() -> None:
    rooms = _rooms()
    student = _students(1)[0]

    assert rooms.confirm(student, "   ") is Refusal.BLANK
    assert rooms.confirm(student, "\x00\x01\t") is Refusal.BLANK
    assert rooms.room_of(student) is None
    assert not rooms


# -- the cap ------------------------------------------------------------------------


def test_the_cap_refuses_a_new_room_but_still_lets_a_student_join_an_existing_one() -> None:
    rooms = _rooms(max_rooms=2)
    one, two, third = _students(3)
    assert rooms.confirm(one, "A") is None
    assert rooms.confirm(two, "B") is None

    assert rooms.confirm(third, "C") is Refusal.FULL
    assert rooms.room_of(third) is None
    assert rooms.confirm(third, "a") is None
    assert rooms.room_of(third) == "A"


def test_a_student_alone_in_a_room_may_move_to_a_new_one_when_the_session_is_at_the_cap() -> None:
    rooms = _rooms(max_rooms=2)
    alone, other = _students(2)
    rooms.confirm(alone, "A")
    rooms.confirm(other, "B")

    assert rooms.confirm(alone, "C") is None

    labels = [s.room_label for s in rooms.statuses(T0, {alone, other})]
    assert labels == ["B", "C"]


def test_a_student_with_company_cannot_open_a_new_room_at_the_cap_and_stays_put() -> None:
    rooms = _rooms(max_rooms=2)
    mover, mate, other = _students(3)
    rooms.confirm(mover, "A")
    rooms.confirm(mate, "A")
    rooms.confirm(other, "B")

    assert rooms.confirm(mover, "C") is Refusal.FULL

    assert rooms.room_of(mover) == "A"
    assert [s.members for s in rooms.statuses(T0, {mover, mate, other})] == [2, 1]


# -- confirming and moving ----------------------------------------------------------


def test_confirming_the_same_room_twice_changes_nothing_and_keeps_what_was_heard() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "Room 1")
    rooms.heard(student, True, T0)

    assert rooms.confirm(student, "Room 1") is None
    assert rooms.confirm(student, " ROOM 1 ") is None

    status = _only(rooms, T0, {student})
    assert (status.status, status.speaking_now) == (RoomStatus.ACTIVE, 1)


def test_moving_rooms_leaves_the_old_one_and_an_emptied_room_disappears() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")

    assert rooms.confirm(student, "B") is None

    assert [s.room_label for s in rooms.statuses(T0, {student})] == ["B"]
    assert rooms.room_of(student) == "B"


def test_leaving_returns_the_label_and_drops_a_room_left_empty() -> None:
    rooms = _rooms()
    student, mate = _students(2)
    rooms.confirm(student, "A")
    rooms.confirm(mate, "A")

    assert rooms.leave(student) == "A"
    assert rooms.leave(student) is None
    assert rooms
    assert rooms.leave(mate) == "A"
    assert not rooms
    assert rooms.statuses(T0, {student, mate}) == []


def test_statuses_come_back_in_label_order() -> None:
    rooms = _rooms()
    for label in ("Zeta", "alpha", "Beta"):
        rooms.confirm(uuid4(), label)

    assert [s.room_label for s in rooms.statuses(T0, set())] == ["alpha", "Beta", "Zeta"]


# -- unknown, active, quiet --------------------------------------------------------


def test_a_room_nobody_has_been_heard_from_is_unknown_not_quiet() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")

    # An hour with no reading at all is not an hour of silence.
    status = _only(rooms, _at(3600), {student})

    assert (status.status, status.silence_seconds, status.members) == (RoomStatus.UNKNOWN, 0, 1)
    assert status.speaking_now == 0


def test_a_speaking_member_makes_the_room_active_and_is_counted() -> None:
    rooms = _rooms()
    talker, listener = _students(2)
    rooms.confirm(talker, "A")
    rooms.confirm(listener, "A")
    rooms.heard(talker, True, T0)
    rooms.heard(listener, False, T0)

    status = _only(rooms, _at(5), {talker, listener})

    assert (status.status, status.speaking_now, status.silence_seconds) == (RoomStatus.ACTIVE, 1, 0)
    assert status.members == 2


def test_silence_is_counted_from_when_the_room_was_first_heard_not_before() -> None:
    long_ago = timedelta(hours=1)
    rooms = _rooms(fresh=long_ago * 2)
    student = _students(1)[0]
    rooms.confirm(student, "A")
    # The room existed for an hour before anyone's microphone reported.
    rooms.heard(student, False, _at(3600))

    status = _only(rooms, _at(3600), {student})

    assert (status.status, status.silence_seconds) == (RoomStatus.ACTIVE, 0)


def test_a_silent_room_goes_quiet_and_then_needs_attention_at_the_limits() -> None:
    rooms = _rooms(fresh=timedelta(hours=1))
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, False, T0)

    observed = [
        (s.status, s.silence_seconds)
        for s in (_only(rooms, _at(t), {student}) for t in (0, 59, 60, 179, 180, 600))
    ]

    assert observed == [
        (RoomStatus.ACTIVE, 0),
        (RoomStatus.ACTIVE, 59),
        (RoomStatus.QUIET, 60),
        (RoomStatus.QUIET, 179),
        (RoomStatus.NEEDS_ATTENTION, 180),
        (RoomStatus.NEEDS_ATTENTION, 600),
    ]


def test_silence_is_counted_from_the_last_voice_when_someone_spoke_after_listening_began() -> None:
    rooms = _rooms(fresh=timedelta(hours=1))
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, False, T0)
    rooms.heard(student, True, _at(30))
    rooms.heard(student, False, _at(40))

    before = _only(rooms, _at(89), {student})
    at_limit = _only(rooms, _at(90), {student})

    assert (before.status, before.silence_seconds) == (RoomStatus.ACTIVE, 59)
    assert (at_limit.status, at_limit.silence_seconds) == (RoomStatus.QUIET, 60)


# -- how fresh a reading is ---------------------------------------------------------


def test_a_voice_reading_older_than_fresh_no_longer_counts() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, True, T0)

    assert _only(rooms, _at(20), {student}).status is RoomStatus.ACTIVE
    stale = _only(rooms, _at(21), {student})

    assert (stale.status, stale.silence_seconds, stale.speaking_now) == (RoomStatus.UNKNOWN, 0, 0)


def test_listening_again_after_a_gap_restarts_the_silence_count() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, False, T0)
    # The device went quiet for 70 seconds, longer than the room's quiet limit.
    assert _only(rooms, _at(70), {student}).status is RoomStatus.UNKNOWN

    rooms.heard(student, False, _at(70))

    resumed = _only(rooms, _at(70), {student})
    assert (resumed.status, resumed.silence_seconds) == (RoomStatus.ACTIVE, 0)


def test_a_reading_that_says_nothing_about_voice_changes_nothing() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")

    rooms.heard(student, None, T0)
    assert _only(rooms, T0, {student}).status is RoomStatus.UNKNOWN

    rooms.heard(student, False, T0)
    rooms.heard(student, None, _at(15))
    # The None at 15 s did not refresh the reading from 0 s.
    assert _only(rooms, _at(25), {student}).status is RoomStatus.UNKNOWN


def test_a_reading_from_a_student_in_no_room_is_ignored() -> None:
    rooms = _rooms()
    student, member = _students(2)
    rooms.confirm(member, "A")

    rooms.heard(student, True, T0)

    assert _only(rooms, T0, {student, member}).status is RoomStatus.UNKNOWN


# -- who counts ---------------------------------------------------------------------


def test_only_connected_members_count_in_members_and_towards_speaking() -> None:
    rooms = _rooms()
    here, gone = _students(2)
    for student in (here, gone):
        rooms.confirm(student, "A")
    rooms.heard(here, False, T0)
    rooms.heard(gone, True, T0)

    status = _only(rooms, T0, {here})

    assert (status.members, status.speaking_now, status.status) == (1, 0, RoomStatus.ACTIVE)


def test_a_room_only_a_departed_member_was_heard_from_is_unknown() -> None:
    rooms = _rooms()
    here, gone = _students(2)
    for student in (here, gone):
        rooms.confirm(student, "A")
    rooms.heard(gone, True, T0)

    status = _only(rooms, T0, {here})

    assert (status.status, status.members, status.speaking_now) == (RoomStatus.UNKNOWN, 1, 0)


def test_a_room_with_nobody_connected_has_no_members_and_is_unknown() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, True, T0)

    status = _only(rooms, T0, set())

    assert (status.status, status.members) == (RoomStatus.UNKNOWN, 0)


def test_forgetting_what_was_heard_keeps_the_student_in_the_room() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, True, T0)

    rooms.unhear(student)

    status = _only(rooms, T0, {student})
    assert (status.status, status.members, status.speaking_now) == (RoomStatus.UNKNOWN, 1, 0)
    assert rooms.room_of(student) == "A"


def test_forgetting_a_student_who_is_in_no_room_does_nothing() -> None:
    rooms = _rooms()
    member, stranger = _students(2)
    rooms.confirm(member, "A")
    rooms.heard(member, True, T0)

    rooms.unhear(stranger)

    assert _only(rooms, T0, {member}).speaking_now == 1


# -- the task -----------------------------------------------------------------------


def test_an_interaction_counts_only_for_a_student_in_a_room() -> None:
    rooms = _rooms()
    member, outsider = _students(2)
    rooms.confirm(member, "A")

    rooms.interacted(outsider)
    assert _only(rooms, T0, {member, outsider}).task_interactions == 0
    rooms.interacted(member)
    rooms.interacted(member)

    assert _only(rooms, T0, {member, outsider}).task_interactions == 2


# -- what the lecturer is told ------------------------------------------------------


def test_news_sends_a_room_only_when_it_changes() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")

    first = rooms.news(uuid4(), T0, {student})
    again = rooms.news(uuid4(), T0, {student})

    assert [r.room_label for r in first.changed] == ["A"]
    assert again.changed == []


def test_news_reports_an_emptied_room_once_with_nobody_in_it() -> None:
    rooms = _rooms()
    student = _students(1)[0]
    rooms.confirm(student, "A")
    rooms.news(uuid4(), T0, {student})
    rooms.leave(student)

    [gone] = rooms.news(uuid4(), T0, {student}).changed

    assert (gone.room_label, gone.members, gone.status) == ("A", 0, RoomStatus.UNKNOWN)
    assert rooms.news(uuid4(), T0, {student}).changed == []


def test_news_alerts_once_per_silence_and_again_after_the_room_is_heard() -> None:
    rooms = _rooms(fresh=timedelta(hours=1))
    session, student = uuid4(), _students(1)[0]
    rooms.confirm(student, "A")
    rooms.heard(student, False, T0)

    [alert] = rooms.news(session, _at(180), {student}).alerts
    assert rooms.news(session, _at(240), {student}).alerts == []
    rooms.heard(student, True, _at(250))
    assert rooms.news(session, _at(250), {student}).alerts == []
    rooms.heard(student, False, _at(251))

    [again] = rooms.news(session, _at(431), {student}).alerts
    assert (alert.session_id, alert.room_label, alert.confidence) == (session, "A", 1.0)
    assert again.alert_id != alert.alert_id
