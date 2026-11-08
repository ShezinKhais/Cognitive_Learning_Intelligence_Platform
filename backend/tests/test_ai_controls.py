"""The lecturer's AI switches: who may set them, the course defaults, and
what each one stops in a running class.

Owner: General CS, Phase 8.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.models.course import Course
from app.models.course_enrollment import CourseLecturer
from app.schemas.events import AiControls, AttentionSignalPayload, ServerEventType
from app.schemas.identity import Role
from app.schemas.session import SessionStatus

from .classroom_support import join_as, make_room, make_row
from .session_support import add_course, add_lecturer, create_session, sign_in_as

ALL_OFF = {
    "auto_checkpoints": False,
    "learning_assistant": False,
    "refocus_nudges": False,
    "engagement_estimates": False,
}


async def _teaching(db, app):  # noqa: ANN001, ANN202
    """A course the development lecturer teaches, and a class of it."""
    client, factory, created = db
    course = await add_course(factory, created)
    async with factory() as seed:
        seed.add(CourseLecturer(course_id=course.id, user_id=LECTURER_ID))
        await seed.commit()
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    return client, factory, course, create_session(client, course)


async def test_a_class_starts_with_every_switch_on(db, app) -> None:
    client, _, _, session = await _teaching(db, app)
    body = client.get(f"/api/v1/sessions/{session['id']}/ai-controls").json()
    assert {k: body[k] for k in ALL_OFF} == dict.fromkeys(ALL_OFF, True)
    assert {k: body["course_defaults"][k] for k in ALL_OFF} == dict.fromkeys(ALL_OFF, True)


async def test_a_change_is_for_this_class_unless_saved_for_the_course(db, app) -> None:
    client, factory, course, session = await _teaching(db, app)
    path = f"/api/v1/sessions/{session['id']}/ai-controls"

    once = client.put(path, json={**ALL_OFF, "learning_assistant": True}).json()
    assert once["learning_assistant"] is True and once["auto_checkpoints"] is False
    assert once["course_defaults"]["auto_checkpoints"] is True
    fresh = create_session(client, course, "Week 2")
    fresh_controls = client.get(f"/api/v1/sessions/{fresh['id']}/ai-controls").json()
    assert fresh_controls["auto_checkpoints"] is True

    saved = client.put(path, json={**ALL_OFF, "apply_to_course": True}).json()
    assert {k: saved["course_defaults"][k] for k in ALL_OFF} == ALL_OFF
    later = create_session(client, course, "Week 3")
    later_controls = client.get(f"/api/v1/sessions/{later['id']}/ai-controls").json()
    assert {k: later_controls[k] for k in ALL_OFF} == ALL_OFF
    # A class that already existed keeps its own switches.
    still = client.get(f"/api/v1/sessions/{fresh['id']}/ai-controls").json()
    assert still["auto_checkpoints"] is True
    async with factory() as look:
        stored = await look.scalar(select(Course).where(Course.id == course.id))
    assert AiControls.of(stored) == AiControls(**ALL_OFF)


async def test_only_a_lecturer_of_the_course_saves_its_defaults(db, app) -> None:
    client, factory, created = db
    course = await add_course(factory, created)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    path = f"/api/v1/sessions/{session['id']}/ai-controls"

    refused = client.put(path, json={**ALL_OFF, "apply_to_course": True})

    assert refused.status_code == 403
    assert client.get(path).json()["auto_checkpoints"] is True


async def test_another_lecturer_or_a_student_cannot_touch_the_switches(db, app) -> None:
    client, factory, created = db
    _, _, _, session = await _teaching(db, app)
    path = f"/api/v1/sessions/{session['id']}/ai-controls"

    sign_in_as(app, await add_lecturer(factory, created), Role.LECTURER)
    assert client.get(path).status_code == 404
    assert client.put(path, json=ALL_OFF).status_code == 404
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    assert client.put(path, json=ALL_OFF).status_code == 403


# -- in the classroom ----------------------------------------------------------------


@pytest.fixture
def room(fake_session_repository):  # noqa: ANN001, ANN201
    return make_room(interval=30.0)


async def test_automatic_checkpoints_off_leaves_only_the_lecturer_sending(room) -> None:
    built, _ = room
    row = make_row()
    built.remember_ai(row.session_id, AiControls(auto_checkpoints=False))
    live = built.activate(row.session_id)
    assert live.countdown.due is None

    await built.set_ai(row.session_id, AiControls(), SessionStatus.ACTIVE)
    assert live.countdown.due is not None
    await built.set_ai(row.session_id, AiControls(auto_checkpoints=False), SessionStatus.ACTIVE)
    assert live.countdown.due is None
    await built.shutdown()


async def test_the_class_is_told_the_switches(room) -> None:
    built, events = room
    row = make_row()
    built.activate(row.session_id)
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)

    await built.set_ai(row.session_id, AiControls(learning_assistant=False), SessionStatus.ACTIVE)

    [state] = socket.of(ServerEventType.SESSION_STATE)[-1:]
    assert state["data"]["ai"]["learning_assistant"] is False
    assert built.state(row.session_id, SessionStatus.ACTIVE).ai.learning_assistant is False
    await built.shutdown()


async def test_engagement_estimates_off_refuses_signals_and_shows_no_scores(room) -> None:
    built, events = room
    row = make_row()
    built.remember_ai(row.session_id, AiControls(engagement_estimates=False))
    built.activate(row.session_id)
    _, student = await join_as(events, row.session_id, Role.STUDENT)

    kept = await built.record_attention(
        row.session_id,
        student,
        AttentionSignalPayload(gaze_on_screen_ratio=0.0, face_present=False, window_seconds=5.0),
    )

    assert kept is False
    assert built.engagement(row.session_id) == []
    await built.shutdown()


async def test_the_switches_are_forgotten_when_the_class_ends(room) -> None:
    built, _ = room
    row = make_row()
    built.remember_ai(row.session_id, AiControls(**ALL_OFF))
    await built.end(row.session_id, SessionStatus.ENDED, 0)
    assert built.ai(row.session_id) == AiControls()
    assert built.ai(uuid4()) == AiControls()


async def test_a_class_has_its_own_pacing_and_can_save_it_for_the_course(db, app) -> None:
    client, _, course, session = await _teaching(db, app)
    path = f"/api/v1/sessions/{session['id']}/ai-controls"
    paced = {"checkpoint_minutes": 5, "answer_seconds": 45}

    saved = client.put(path, json={**paced, "apply_to_course": True})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["checkpoint_minutes"], saved.json()["answer_seconds"]) == (5, 45)
    later = create_session(client, course, "Workshop 2")
    inherited = client.get(f"/api/v1/sessions/{later['id']}/ai-controls").json()
    assert (inherited["checkpoint_minutes"], inherited["answer_seconds"]) == (5, 45)

    assert client.put(path, json={"checkpoint_minutes": 1}).status_code == 422
    assert client.put(path, json={"answer_seconds": 5000}).status_code == 422
    cleared = client.put(path, json={}).json()
    assert (cleared["checkpoint_minutes"], cleared["answer_seconds"]) == (None, None)


def test_the_classroom_follows_the_class_pacing() -> None:
    from datetime import timedelta
    from uuid import uuid4

    from app.realtime.classroom import Classroom

    built = Classroom()
    paced, usual = uuid4(), uuid4()
    built.remember_ai(paced, AiControls(checkpoint_minutes=5, answer_seconds=45))

    assert built._window(paced) == timedelta(seconds=45)
    assert built._window(usual) == timedelta(seconds=30)
    for _ in range(20):
        wait = built._next_wait(paced)
        assert wait is not None
        assert timedelta(seconds=270) <= wait <= timedelta(seconds=330)
