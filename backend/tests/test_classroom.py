"""The running side of a live session: delivery, the response window, answers
and the question cycle.

Owner: General CS. The database is replaced by a fake repository so these
exercise the timing and the rules alone; test_session_lifecycle.py covers the
routes against a real database.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.errors import ConflictError
from app.realtime import classroom as classroom_module
from app.realtime.classroom import Classroom, Submission
from app.realtime.hub import Connection, SessionHub
from app.schemas.events import AnswerSubmitPayload, PromptAckPayload, ServerEventType
from app.schemas.identity import Role
from app.schemas.session import SessionStatus


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        return None

    def of(self, event_type: ServerEventType) -> list[dict]:
        return [m for m in self.sent if m["type"] == event_type.value]


@dataclass
class _Question:
    question_text: str = "Which planet is largest?"
    options: list[str] | None = field(default_factory=lambda: ["Mars", "Jupiter", "Venus"])
    correct_option: int | None = 1
    source_slide: int | None = 4
    question_id: UUID = field(default_factory=uuid4)


class _Db:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> _Db:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Repository:
    """Stands in for SessionRepository: a queue of staged questions."""

    staged: list[_Question] = []
    rows: dict[UUID, SimpleNamespace] = {}

    def __init__(self, db: object) -> None:
        pass

    async def claim_for_delivery(self, row, question_id=None):  # noqa: ANN001, ANN201
        for question in _Repository.staged:
            if question_id is None or question.question_id == question_id:
                _Repository.staged.remove(question)
                return question
        return None

    async def count_delivered(self, session_id: UUID) -> int:
        return 0

    async def get(self, session_id: UUID, *, for_update: bool = False):  # noqa: ANN201
        return _Repository.rows.get(session_id)


@pytest.fixture(autouse=True)
def _fake_repository(monkeypatch: pytest.MonkeyPatch):
    _Repository.staged = []
    _Repository.rows = {}
    monkeypatch.setattr(classroom_module, "SessionRepository", _Repository)


def _room(
    interval: float = 3600.0, window: float = 30.0, prompts: int = 3, prompt_ttl: float = 60.0
) -> tuple[Classroom, SessionHub]:
    events = SessionHub()
    settings = SimpleNamespace(
        checkpoint_interval_seconds=interval,
        checkpoint_response_window_seconds=window,
        dynamic_prompt_max_per_student=prompts,
        attention_prompt_ttl_seconds=prompt_ttl,
    )
    room = Classroom(events=events, sessions=lambda: _Db, settings=lambda: settings)
    return room, events


def _row(session_id: UUID | None = None) -> SimpleNamespace:
    row = SimpleNamespace(
        session_id=session_id or uuid4(), status=SessionStatus.ACTIVE.value, paused_at=None
    )
    _Repository.rows[row.session_id] = row
    return row


async def _join(events: SessionHub, session_id: UUID, role: Role, user: UUID | None = None):
    socket = _Socket()
    user = user or uuid4()
    await events.join(Connection(socket, user, session_id, role))  # type: ignore[arg-type]
    return socket, user


def _answer(question_id: UUID, option: int | None = 1, text: str | None = None):
    return AnswerSubmitPayload(
        question_id=question_id, selected_option=option, free_text=text, client_elapsed_ms=900
    )


async def _deliver(room: Classroom, row: SimpleNamespace) -> _Question:
    question = _Question()
    _Repository.staged.append(question)
    assert await room.deliver(_Db(), row) is not None  # type: ignore[arg-type]
    return question


async def test_a_delivered_question_reaches_everyone_without_its_answer() -> None:
    room, events = _room(window=30)
    row = _row()
    student, _ = await _join(events, row.session_id, Role.STUDENT)
    lecturer, _ = await _join(events, row.session_id, Role.LECTURER)

    question = await _deliver(room, row)

    for socket in (student, lecturer):
        [event] = socket.of(ServerEventType.QUESTION_DELIVERED)
        assert event["data"]["question_id"] == str(question.question_id)
        assert event["data"]["options"] == question.options
        assert event["data"]["window_seconds"] == 30
        assert "correct_option" not in event["data"]
    await room.shutdown()


async def test_the_delivery_is_recorded_before_anyone_is_told() -> None:
    room, events = _room()
    row = _row()
    db = _Db()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)

    async def commit() -> None:
        assert socket.of(ServerEventType.QUESTION_DELIVERED) == []
        db.commits += 1

    db.commit = commit  # type: ignore[method-assign]
    _Repository.staged.append(_Question())
    await room.deliver(db, row)  # type: ignore[arg-type]

    assert db.commits == 1
    assert socket.of(ServerEventType.QUESTION_DELIVERED)
    await room.shutdown()


async def test_a_second_question_is_refused_while_one_is_open() -> None:
    room, _ = _room()
    row = _row()
    await _deliver(room, row)
    _Repository.staged.append(_Question())

    with pytest.raises(ConflictError):
        await room.deliver(_Db(), row)  # type: ignore[arg-type]
    await room.shutdown()


async def test_nothing_staged_delivers_nothing() -> None:
    room, events = _room()
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)

    assert await room.deliver(_Db(), row) is None  # type: ignore[arg-type]
    assert socket.sent == []
    await room.shutdown()


async def test_the_window_closes_itself_and_reports_who_answered() -> None:
    room, events = _room(window=0.2)
    row = _row()
    watcher, _ = await _join(events, row.session_id, Role.LECTURER)
    _, answering = await _join(events, row.session_id, Role.STUDENT)
    await _join(events, row.session_id, Role.STUDENT)
    question = await _deliver(room, row)

    receipt = await room.submit(
        row.session_id, answering, Role.STUDENT, _answer(question.question_id)
    )
    assert receipt.accepted
    await asyncio.sleep(0.4)

    [closed] = watcher.of(ServerEventType.QUESTION_CLOSED)
    assert closed["data"] == {
        "question_id": str(question.question_id),
        "reason": "window_elapsed",
        "respondents": 1,
        "eligible": 2,
    }
    delivered = watcher.of(ServerEventType.QUESTION_DELIVERED)[0]
    assert closed["seq"] > delivered["seq"]
    # The lecturer is watching, not answering, so is not eligible.
    await room.shutdown()


async def test_a_student_who_joins_late_and_answers_counts_as_eligible() -> None:
    room, events = _room(window=0.2)
    row = _row()
    watcher, _ = await _join(events, row.session_id, Role.LECTURER)
    question = await _deliver(room, row)
    _, late = await _join(events, row.session_id, Role.STUDENT)

    assert (
        await room.submit(row.session_id, late, Role.STUDENT, _answer(question.question_id))
    ).accepted
    await asyncio.sleep(0.4)

    [closed] = watcher.of(ServerEventType.QUESTION_CLOSED)
    assert (closed["data"]["respondents"], closed["data"]["eligible"]) == (1, 1)
    await room.shutdown()


async def test_the_next_question_can_go_out_once_the_window_has_closed() -> None:
    room, _ = _room(window=0.1)
    row = _row()
    await _deliver(room, row)
    await asyncio.sleep(0.25)

    await _deliver(room, row)
    await room.shutdown()


@pytest.mark.parametrize(
    ("role", "answer", "reason"),
    [
        (Role.LECTURER, {}, "Only students answer questions."),
        (Role.ADMIN, {}, "Only students answer questions."),
        (Role.STUDENT, {"option": 3}, "That option is not one of the choices."),
        (Role.STUDENT, {"option": None, "text": "Jupiter"}, "Choose one of the options."),
        (Role.STUDENT, {"other_question": True}, "This question is not open."),
    ],
)
async def test_answers_that_do_not_count_are_refused_with_a_reason(
    role: Role, answer: dict, reason: str
) -> None:
    room, _ = _room()
    row = _row()
    question = await _deliver(room, row)
    target = uuid4() if answer.pop("other_question", False) else question.question_id

    receipt = await room.submit(row.session_id, uuid4(), role, _answer(target, **answer))

    assert (receipt.accepted, receipt.reason) == (False, reason)
    await room.shutdown()


async def test_a_student_answers_each_question_once() -> None:
    room, _ = _room()
    row = _row()
    question = await _deliver(room, row)
    student = uuid4()

    first = await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))
    second = await room.submit(
        row.session_id, student, Role.STUDENT, _answer(question.question_id, 0)
    )

    assert first.accepted
    assert (second.accepted, second.reason) == (False, "You have already answered this question.")
    await room.shutdown()


async def test_an_answer_after_the_window_is_refused_even_before_it_is_closed() -> None:
    """The close runs on a timer that can fire late. The deadline is closes_at,
    not whenever the timer gets round to it."""
    room, _ = _room()
    row = _row()
    question = await _deliver(room, row)
    live = room._live[row.session_id]
    assert live.open is not None
    live.open.closes_at = datetime.now(UTC) - timedelta(milliseconds=1)

    receipt = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, _answer(question.question_id)
    )

    assert (receipt.accepted, receipt.reason) == (False, "The response window has closed.")
    await room.shutdown()


async def test_a_free_text_question_takes_words_not_an_option() -> None:
    room, _ = _room()
    row = _row()
    question = _Question(options=None, correct_option=None)
    _Repository.staged.append(question)
    await room.deliver(_Db(), row)  # type: ignore[arg-type]

    by_option = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, _answer(question.question_id)
    )
    in_words = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, _answer(question.question_id, None, "Jupiter")
    )

    assert (by_option.accepted, by_option.reason) == (
        False,
        "Answer this question in your own words.",
    )
    assert in_words.accepted
    await room.shutdown()


async def test_the_recorder_receives_each_accepted_answer() -> None:
    room, _ = _room()
    recorded: list[Submission] = []

    class Recorder:
        async def record(self, submission: Submission) -> None:
            recorded.append(submission)

    room.recorder = Recorder()
    row = _row()
    question = await _deliver(room, row)
    student = uuid4()

    await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id, 2))

    [submission] = recorded
    assert (submission.user_id, submission.selected_option, submission.client_elapsed_ms) == (
        student,
        2,
        900,
    )
    await room.shutdown()


async def test_an_answer_that_could_not_be_saved_can_be_sent_again() -> None:
    room, _ = _room()
    failures = [RuntimeError("database gone")]

    class Recorder:
        async def record(self, submission: Submission) -> None:
            if failures:
                raise failures.pop()

    room.recorder = Recorder()
    row = _row()
    question = await _deliver(room, row)
    student = uuid4()

    first = await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))
    retry = await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))

    assert not first.accepted
    assert "could not be saved" in (first.reason or "")
    assert retry.accepted
    await room.shutdown()


async def test_ending_closes_the_open_question_then_announces_the_end() -> None:
    room, events = _room()
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    question = await _deliver(room, row)

    await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    closed, state = socket.sent[-2:]
    assert (closed["type"], closed["data"]["reason"]) == ("question.closed", "session_ended")
    assert closed["data"]["question_id"] == str(question.question_id)
    assert (state["type"], state["data"]["status"], state["data"]["questions_delivered"]) == (
        "session.state",
        "ended",
        1,
    )
    assert room.get_running(row.session_id) is None
    assert events.tracked_stream_count() == 0


async def test_an_answer_after_the_end_is_refused() -> None:
    room, _ = _room()
    row = _row()
    question = await _deliver(room, row)
    await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    receipt = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, _answer(question.question_id)
    )

    assert not receipt.accepted


async def test_the_cycle_delivers_the_next_question_on_its_own() -> None:
    room, events = _room(interval=0.15, window=0.05)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    _Repository.staged.extend([_Question(), _Question()])

    room.activate(row.session_id)
    await asyncio.sleep(0.5)

    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 2
    assert len(socket.of(ServerEventType.QUESTION_CLOSED)) == 2
    await room.shutdown()


async def test_a_manual_question_postpones_the_cycle() -> None:
    room, events = _room(interval=0.3, window=0.05)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    room.activate(row.session_id)
    await asyncio.sleep(0.2)
    await _deliver(room, row)
    _Repository.staged.append(_Question())

    # Without the postponement the cycle would fire 0.1s from now.
    await asyncio.sleep(0.2)

    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await room.shutdown()


async def test_the_cycle_stops_once_the_session_is_no_longer_active() -> None:
    room, _ = _room(interval=0.05)
    row = _row()
    live = room.activate(row.session_id)
    row.status = SessionStatus.ENDED.value

    await asyncio.sleep(0.2)

    assert live.cycle is not None and live.cycle.done()
    assert room.get_running(row.session_id) is None


async def test_a_failed_scheduled_delivery_does_not_stop_the_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, events = _room(interval=0.1, window=0.02)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    real_claim = _Repository.claim_for_delivery
    calls = 0

    async def flaky(self, live, question_id=None):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database hiccup")
        return await real_claim(self, live, question_id)

    monkeypatch.setattr(_Repository, "claim_for_delivery", flaky)
    _Repository.staged.append(_Question())
    room.activate(row.session_id)

    await asyncio.sleep(0.35)

    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await room.shutdown()


async def test_a_joining_client_is_given_the_open_question() -> None:
    room, events = _room()
    row = _row()
    question = await _deliver(room, row)
    answered = uuid4()
    await room.submit(row.session_id, answered, Role.STUDENT, _answer(question.question_id))

    fresh = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.STUDENT)
    again = room.welcome(row.session_id, SessionStatus.ACTIVE, answered, Role.STUDENT)
    staff = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.LECTURER)

    assert [t for t, _ in fresh] == [
        ServerEventType.SESSION_STATE,
        ServerEventType.QUESTION_DELIVERED,
    ]
    assert fresh[0][1]["active_question_id"] == str(question.question_id)
    assert fresh[1][1]["question_id"] == str(question.question_id)
    assert [t for t, _ in again] == [ServerEventType.SESSION_STATE]
    # The lecturer's panel reconnecting mid-question needs the question and
    # its timer too; it carries no answer key.
    assert [t for t, _ in staff] == [
        ServerEventType.SESSION_STATE,
        ServerEventType.QUESTION_DELIVERED,
    ]
    await room.shutdown()


async def test_the_welcome_reports_a_start_or_end_that_happened_after_admission() -> None:
    room, _ = _room()
    started, ended = _row(), _row()
    room.activate(started.session_id)

    [(_, now_active)] = room.welcome(started.session_id, SessionStatus.PREPARED, uuid4(), None)
    [(_, now_ended)] = room.welcome(ended.session_id, SessionStatus.ACTIVE, uuid4(), None)

    assert now_active["status"] == "active"
    assert now_ended["status"] == "ended"
    await room.shutdown()


async def test_shutdown_stops_every_timer() -> None:
    room, _ = _room()
    row = _row()
    await _deliver(room, row)
    live = room._live[row.session_id]
    assert live.open is not None
    timers = [live.cycle, live.open.closer]

    await room.shutdown()

    assert all(task is not None and task.done() for task in timers)
    assert room.get_running(row.session_id) is None


# -- bugs found in review -----------------------------------------------------


async def test_a_socket_admitted_before_the_end_does_not_revive_the_session() -> None:
    """The socket read the row while it was active, the lecturer ended it,
    and then the socket restored it: a question cycle ran for a session that
    had ended, and the student was told it was still active."""
    room, _ = _room()
    row = _row()
    room.activate(row.session_id)
    stale = SimpleNamespace(**vars(row))

    row.status = SessionStatus.ENDED.value
    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)

    assert await room.restore(_Db(), stale) is None  # type: ignore[arg-type]
    assert room.get_running(row.session_id) is None
    [(_, state)] = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.STUDENT)
    assert state["status"] == "ended"


async def test_an_end_while_a_restore_is_reading_the_database_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, _ = _room()
    row = _row()
    reading, release = asyncio.Event(), asyncio.Event()

    async def slow_count(self, session_id: UUID) -> int:  # noqa: ANN001
        reading.set()
        await release.wait()
        return 0

    monkeypatch.setattr(_Repository, "count_delivered", slow_count)
    restoring = asyncio.create_task(room.restore(_Db(), row))  # type: ignore[arg-type]
    await reading.wait()
    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)
    release.set()

    assert await restoring is None
    assert room.get_running(row.session_id) is None


async def test_a_session_cancelled_after_admission_is_not_reported_as_waiting() -> None:
    room, _ = _room()
    session_id = uuid4()

    await room.end(session_id, SessionStatus.CANCELLED, delivered=0)

    [(_, state)] = room.welcome(session_id, SessionStatus.PREPARED, uuid4(), Role.STUDENT)
    assert state["status"] == "cancelled"


async def test_a_student_shown_the_question_on_joining_is_eligible_to_answer_it() -> None:
    room, events = _room(window=0.2)
    row = _row()
    watcher, _ = await _join(events, row.session_id, Role.LECTURER)
    await _deliver(room, row)
    late = uuid4()

    room.welcome(row.session_id, SessionStatus.ACTIVE, late, Role.STUDENT)
    await asyncio.sleep(0.4)

    [closed] = watcher.of(ServerEventType.QUESTION_CLOSED)
    assert (closed["data"]["respondents"], closed["data"]["eligible"]) == (0, 1)
    await room.shutdown()


async def test_participants_are_students_each_counted_once() -> None:
    room, events = _room()
    row = _row()
    student = uuid4()
    await _join(events, row.session_id, Role.STUDENT, student)
    await _join(events, row.session_id, Role.STUDENT, student)
    await _join(events, row.session_id, Role.STUDENT)
    await _join(events, row.session_id, Role.LECTURER)

    assert room.state(row.session_id, SessionStatus.ACTIVE).participant_count == 2


async def test_a_recorder_that_hangs_still_gets_the_student_a_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(classroom_module, "RECORD_TIMEOUT_SECONDS", 0.05)
    room, _ = _room()

    class Recorder:
        async def record(self, submission: Submission) -> None:
            await asyncio.sleep(10)

    room.recorder = Recorder()
    row = _row()
    question = await _deliver(room, row)

    receipt = await asyncio.wait_for(
        room.submit(row.session_id, uuid4(), Role.STUDENT, _answer(question.question_id)), 1
    )

    assert not receipt.accepted
    assert receipt.reason == "Your answer could not be saved. Please submit it again."
    await room.shutdown()


async def test_a_failed_save_after_the_window_does_not_invite_a_resubmission() -> None:
    room, _ = _room(window=0.1)

    class Recorder:
        async def record(self, submission: Submission) -> None:
            await asyncio.sleep(0.2)
            raise RuntimeError("database gone")

    room.recorder = Recorder()
    row = _row()
    question = await _deliver(room, row)

    receipt = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, _answer(question.question_id)
    )

    assert receipt.reason == "Your answer could not be saved."
    await room.shutdown()


async def test_an_interval_of_zero_leaves_delivery_to_the_lecturer() -> None:
    room, _ = _room(interval=0)
    row = _row()

    live = room.activate(row.session_id)

    assert live.cycle is None
    await _deliver(room, row)
    await room.shutdown()


# -- pause ------------------------------------------------------------------


async def test_a_paused_session_delivers_nothing_until_it_resumes() -> None:
    room, events = _room(interval=0.15, window=0.05)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    _Repository.staged.extend([_Question(), _Question()])
    cycle = room.activate(row.session_id).cycle

    await room.pause(_Db(), row)  # type: ignore[arg-type]
    await asyncio.sleep(0.3)
    # Stopped, not merely refused each time, or resuming would leave two.
    assert cycle is not None and cycle.cancelled()
    assert socket.of(ServerEventType.QUESTION_DELIVERED) == []
    with pytest.raises(ConflictError):
        await room.deliver(_Db(), row)  # type: ignore[arg-type]

    await room.resume(_Db(), row)  # type: ignore[arg-type]
    await asyncio.sleep(0.25)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    states = [e["data"]["paused"] for e in socket.of(ServerEventType.SESSION_STATE)]
    assert states == [True, False]
    await room.shutdown()


async def test_pausing_is_recorded_before_it_is_announced() -> None:
    room, _ = _room()
    row = _row()
    room.activate(row.session_id)
    db = _Db()

    await room.pause(db, row)  # type: ignore[arg-type]

    assert row.paused_at is not None and db.commits == 1
    await room.resume(db, row)  # type: ignore[arg-type]
    assert row.paused_at is None and db.commits == 2
    await room.shutdown()


async def test_resuming_keeps_the_time_that_was_left() -> None:
    room, _ = _room(interval=10)
    row = _row()
    live = room.activate(row.session_id)
    live.next_due = datetime.now(UTC) + timedelta(seconds=4)

    await room.pause(_Db(), row)  # type: ignore[arg-type]
    await room.resume(_Db(), row)  # type: ignore[arg-type]

    left = (live.next_due - datetime.now(UTC)).total_seconds()
    assert 3 < left <= 4
    await room.shutdown()


async def test_a_question_open_at_the_pause_runs_to_the_end_of_its_window() -> None:
    room, events = _room(window=0.2)
    row = _row()
    socket, student = await _join(events, row.session_id, Role.STUDENT)
    question = await _deliver(room, row)

    await room.pause(_Db(), row)  # type: ignore[arg-type]
    receipt = await room.submit(
        row.session_id, student, Role.STUDENT, _answer(question.question_id)
    )
    await asyncio.sleep(0.35)

    assert receipt.accepted
    [closed] = socket.of(ServerEventType.QUESTION_CLOSED)
    assert closed["data"]["reason"] == "window_elapsed"
    await room.shutdown()


async def test_a_session_paused_before_a_restart_stays_paused() -> None:
    room, _ = _room(interval=0.05)
    row = _row()
    row.paused_at = datetime.now(UTC)

    live = await room.restore(_Db(), row)  # type: ignore[arg-type]

    assert live is not None and live.paused and live.cycle is None
    [(_, state)] = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.STUDENT)
    assert state["paused"] is True
    await room.shutdown()


async def test_ending_a_paused_session_reports_it_ended_not_paused() -> None:
    room, events = _room()
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    room.activate(row.session_id)
    await room.pause(_Db(), row)  # type: ignore[arg-type]

    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)

    state = socket.of(ServerEventType.SESSION_STATE)[-1]["data"]
    assert (state["status"], state["paused"]) == ("ended", False)


# -- attention prompts --------------------------------------------------------


@dataclass
class _PromptLog:
    outcomes: list = field(default_factory=list)

    async def record_prompt(self, outcome) -> None:  # noqa: ANN001
        self.outcomes.append(outcome)


async def _prompted_room(**settings: float):  # noqa: ANN202
    room, events = _room(**settings)  # type: ignore[arg-type]
    row = _row()
    room.activate(row.session_id)
    socket, student = await _join(events, row.session_id, Role.STUDENT)
    log = _PromptLog()
    room.prompt_recorder = log
    return room, events, row, socket, student, log


async def test_a_prompt_reaches_only_its_student_outside_the_sequence() -> None:
    room, events, row, socket, student, _ = await _prompted_room()
    classmate, _ = await _join(events, row.session_id, Role.STUDENT)
    lecturer, _ = await _join(events, row.session_id, Role.LECTURER)

    sent = await room.prompt_student(row.session_id, student, "Still with us?")

    assert sent is not None and sent.escalation == 1
    [prompt] = socket.of(ServerEventType.PROMPT_ATTENTION)
    assert (prompt["seq"], prompt["data"]["prompt_id"]) == (0, str(sent.prompt_id))
    assert classmate.sent == lecturer.sent == []
    await room.shutdown()


async def test_one_prompt_at_a_time_and_no_more_than_the_limit() -> None:
    room, _, row, _, student, _ = await _prompted_room(prompts=2)

    first = await room.prompt_student(row.session_id, student, "Still with us?")
    assert await room.prompt_student(row.session_id, student, "Again?") is None
    assert first is not None
    await room.acknowledge_prompt(
        row.session_id, student, PromptAckPayload(prompt_id=first.prompt_id, dismissed=True)
    )
    second = await room.prompt_student(row.session_id, student, "Still with us?")
    assert second is not None
    await room.acknowledge_prompt(
        row.session_id, student, PromptAckPayload(prompt_id=second.prompt_id)
    )

    assert await room.prompt_student(row.session_id, student, "Third?") is None
    await room.shutdown()


async def test_escalation_counts_prompts_in_a_row_not_answered_with_im_here() -> None:
    room, _, row, _, student, log = await _prompted_room(prompt_ttl=0.05)

    first = await room.prompt_student(row.session_id, student, "Still with us?")
    await asyncio.sleep(0.1)  # expires unanswered
    second = await room.prompt_student(row.session_id, student, "Still with us?")
    assert second is not None
    await room.acknowledge_prompt(
        row.session_id, student, PromptAckPayload(prompt_id=second.prompt_id)
    )
    third = await room.prompt_student(row.session_id, student, "Still with us?")

    assert first is not None and third is not None
    assert (first.escalation, second.escalation, third.escalation) == (1, 2, 1)
    assert [o.result.value for o in log.outcomes] == ["expired", "acknowledged"]
    await room.shutdown()


async def test_a_dismissed_prompt_does_not_reset_the_escalation() -> None:
    room, _, row, _, student, log = await _prompted_room()

    first = await room.prompt_student(row.session_id, student, "Still with us?")
    assert first is not None
    await room.acknowledge_prompt(
        row.session_id, student, PromptAckPayload(prompt_id=first.prompt_id, dismissed=True)
    )
    second = await room.prompt_student(row.session_id, student, "Still with us?")

    assert second is not None and second.escalation == 2
    assert log.outcomes[0].result.value == "dismissed"
    await room.shutdown()


async def test_a_student_cannot_answer_another_students_prompt() -> None:
    room, events, row, _, student, log = await _prompted_room()
    _, other = await _join(events, row.session_id, Role.STUDENT)
    sent = await room.prompt_student(row.session_id, student, "Still with us?")
    assert sent is not None

    stolen = await room.acknowledge_prompt(
        row.session_id, other, PromptAckPayload(prompt_id=sent.prompt_id)
    )
    unknown = await room.acknowledge_prompt(
        row.session_id, student, PromptAckPayload(prompt_id=uuid4())
    )

    assert (stolen, unknown) == (False, False)
    assert log.outcomes == []
    await room.shutdown()


async def test_no_prompt_to_a_student_who_is_away_or_answering() -> None:
    room, _, row, _, student, _ = await _prompted_room()

    assert await room.prompt_student(row.session_id, uuid4(), "Not connected") is None
    await _deliver(room, row)
    assert await room.prompt_student(row.session_id, student, "Answering") is None
    await room.shutdown()


async def test_no_prompt_while_the_session_is_paused() -> None:
    room, _, row, _, student, _ = await _prompted_room()

    await room.pause(_Db(), row)  # type: ignore[arg-type]

    assert await room.prompt_student(row.session_id, student, "Paused") is None
    await room.shutdown()


async def test_a_reconnecting_student_is_shown_their_waiting_prompt() -> None:
    room, _, row, _, student, _ = await _prompted_room()
    sent = await room.prompt_student(row.session_id, student, "Still with us?")
    assert sent is not None

    mine = room.welcome(row.session_id, SessionStatus.ACTIVE, student, Role.STUDENT)
    theirs = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.STUDENT)

    assert mine[-1] == (ServerEventType.PROMPT_ATTENTION, sent.model_dump(mode="json"))
    assert [t for t, _ in theirs] == [ServerEventType.SESSION_STATE]
    await room.shutdown()


async def test_ending_records_a_waiting_prompt_as_expired() -> None:
    room, _, row, _, student, log = await _prompted_room()
    sent = await room.prompt_student(row.session_id, student, "Still with us?")

    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)

    [outcome] = log.outcomes
    assert sent is not None
    assert (outcome.prompt_id, outcome.result.value) == (sent.prompt_id, "expired")


async def test_a_blank_prompt_is_a_programming_error() -> None:
    room, _, row, _, student, _ = await _prompted_room()

    with pytest.raises(ValueError, match="prompt message"):
        await room.prompt_student(row.session_id, student, "   ")
    await room.shutdown()
