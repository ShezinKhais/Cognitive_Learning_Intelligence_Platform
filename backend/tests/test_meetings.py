"""Teams meetings starting and ending sessions, through the mock adapter's
routes, against a real database.

Owner: General CS, Phase 4. The directory is the in-memory one; BBIS's store
replaces it.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.models.session import Session as SessionModel
from app.schemas.identity import Role
from app.services.meeting_directory import InMemoryMeetingDirectory, Meetings, meetings

from .session_support import add_course, add_lecturer, add_question, create_session, sign_in_as


@pytest.fixture(autouse=True)
def _fresh_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meetings, "directory", InMemoryMeetingDirectory())


def _meeting() -> str:
    return f"19:meeting_{uuid4().hex}@thread.v2"


def _event(client, kind: str, meeting_id: str, **extra):  # noqa: ANN001, ANN003, ANN202
    return client.post(
        "/api/v1/meetings/events", json={"kind": kind, "meeting_id": meeting_id, **extra}
    )


async def _linked_session(db, app) -> tuple[dict, str]:  # noqa: ANN001
    client, factory, created = db
    course = await add_course(factory, created)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    meeting = _meeting()
    linked = client.put(f"/api/v1/meetings/{meeting}", json={"session_id": session["id"]})
    assert linked.status_code == 200, linked.text
    return linked.json(), meeting


async def test_a_linked_session_is_held_in_teams_and_reports_its_meeting(db, app) -> None:
    client, factory, _ = db
    linked, meeting = await _linked_session(db, app)

    async with factory() as check:
        mode = await check.scalar(
            select(SessionModel.mode).where(SessionModel.session_id == UUID(linked["id"]))
        )
    assert mode == "teams"
    assert linked["teams_meeting_id"] == meeting
    started = client.post(f"/api/v1/sessions/{linked['id']}/start")
    assert started.json()["teams_meeting_id"] == meeting


async def test_the_meeting_starting_and_ending_runs_the_session(db, app) -> None:
    client, _, _ = db
    linked, meeting = await _linked_session(db, app)

    started = _event(client, "started", meeting)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "active"

    ended = _event(client, "ended", meeting)
    assert (ended.json()["id"], ended.json()["status"]) == (linked["id"], "ended")


async def test_an_event_delivered_twice_changes_nothing_the_second_time(db, app) -> None:
    """Teams redelivers. A second start must not be refused as a conflict,
    or the bot retries a delivery that already worked."""
    client, _, _ = db
    _, meeting = await _linked_session(db, app)

    for kind, status in (("started", "active"), ("ended", "ended")):
        first, second = _event(client, kind, meeting), _event(client, kind, meeting)
        assert (first.status_code, second.status_code) == (200, 200)
        assert first.json()["status"] == second.json()["status"] == status


async def test_a_meeting_that_ends_before_the_class_starts_cancels_it(db, app) -> None:
    client, _, _ = db
    _, meeting = await _linked_session(db, app)

    assert _event(client, "ended", meeting).json()["status"] == "cancelled"


async def test_a_meeting_that_starts_unlinked_gets_a_session_for_its_course(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    await add_question(db, course, LECTURER_ID)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    meeting = _meeting()

    started = _event(client, "started", meeting, course_code=course.code, title="Week 3")

    assert started.status_code == 200, started.text
    body = started.json()
    assert (body["status"], body["title"], body["course_code"]) == ("active", "Week 3", course.code)
    assert body["teams_meeting_id"] == meeting


async def test_a_created_session_that_cannot_start_stays_linked_for_the_retry(db, app) -> None:
    """Nothing is staged, so the start is refused. The session it created is
    kept and linked, so the next start event finds it rather than making
    another."""
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    meeting = _meeting()

    refused = _event(client, "started", meeting, course_code=course.code)
    assert refused.status_code == 409

    session_id = await meetings.directory.session_for(meeting)
    assert session_id is not None
    await add_question(db, course, LECTURER_ID)
    retried = _event(client, "started", meeting, course_code=course.code)
    assert (retried.json()["id"], retried.json()["status"]) == (str(session_id), "active")
    assert retried.json()["title"] == "Teams meeting"


async def test_an_unlinked_meeting_with_no_course_is_not_found(db, app) -> None:
    client, _, _ = db
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert _event(client, "started", _meeting()).status_code == 404
    assert _event(client, "ended", _meeting(), course_code="ANY").status_code == 404


async def test_another_lecturer_cannot_link_or_drive_a_session(db, app) -> None:
    client, factory, created = db
    linked, meeting = await _linked_session(db, app)
    sign_in_as(app, await add_lecturer(factory, created), Role.LECTURER)

    assert _event(client, "started", meeting).status_code == 404
    relink = client.put(f"/api/v1/meetings/{_meeting()}", json={"session_id": linked["id"]})
    assert relink.status_code == 404


async def test_students_cannot_send_meeting_events(db, app) -> None:
    client, _, _ = db
    _, meeting = await _linked_session(db, app)
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    assert _event(client, "started", meeting).status_code == 403


async def test_a_finished_session_cannot_be_linked(db, app) -> None:
    client, _, _ = db
    linked, meeting = await _linked_session(db, app)
    _event(client, "ended", meeting)

    again = client.put(f"/api/v1/meetings/{_meeting()}", json={"session_id": linked["id"]})
    assert again.status_code == 409


# -- the directory, no database -------------------------------------------------


async def test_relinking_either_side_drops_the_old_partner() -> None:
    directory = InMemoryMeetingDirectory()
    first, second = uuid4(), uuid4()
    await directory.link("m1", first)

    await directory.link("m1", second)
    assert (await directory.session_for("m1"), await directory.meeting_for(first)) == (
        second,
        None,
    )

    await directory.link("m2", second)
    assert (await directory.session_for("m1"), await directory.meeting_for(second)) == (
        None,
        "m2",
    )


def test_production_will_not_start_with_meeting_links_kept_in_memory() -> None:
    production = Meetings(settings=lambda: SimpleNamespace(is_production=True))

    with pytest.raises(RuntimeError, match="no MeetingDirectory is registered"):
        production.check_wiring()

    production.directory = object()  # type: ignore[assignment]
    production.check_wiring()


async def test_a_meeting_holding_another_lecturers_session_cannot_be_taken(db, app) -> None:
    """The link decides whose class a meeting starts and ends. Replacing it
    would hand one lecturer another's meeting, and unlink theirs."""
    client, factory, created = db
    theirs, meeting = await _linked_session(db, app)
    other = await add_lecturer(factory, created)
    course = await add_course(factory, created)
    sign_in_as(app, other, Role.LECTURER)
    mine = create_session(client, course)

    taken = client.put(f"/api/v1/meetings/{meeting}", json={"session_id": mine["id"]})

    assert taken.status_code == 409
    assert await meetings.directory.session_for(meeting) == UUID(theirs["id"])


async def test_a_lecturer_can_move_their_meeting_to_another_of_their_sessions(db, app) -> None:
    client, factory, created = db
    first, meeting = await _linked_session(db, app)
    second = create_session(client, await add_course(factory, created))

    moved = client.put(f"/api/v1/meetings/{meeting}", json={"session_id": second["id"]})

    assert moved.status_code == 200
    assert await meetings.directory.meeting_for(UUID(first["id"])) is None
