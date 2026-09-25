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
from app.realtime import attention as attention_module
from app.realtime import classroom as classroom_module
from app.realtime.classroom import Classroom
from app.realtime.hub import Connection, SessionHub
from app.realtime.recorders import (
    Attendance,
    ClosedQuestion,
    QuestionComprehension,
    Submission,
)
from app.schemas.events import (
    AnswerSubmitPayload,
    AttentionSignalPayload,
    FeedbackResultPayload,
    PromptAckPayload,
    ServerEventType,
)
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
    question_type: str | None = None

    def __post_init__(self) -> None:
        if self.question_type is None:
            self.question_type = "mcq" if self.options else "free_text"


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
    # What each claim was told about the delivery it records.
    deliveries: list[dict] = []
    rows: dict[UUID, SimpleNamespace] = {}

    def __init__(self, db: object) -> None:
        pass

    async def claim_for_delivery(self, row, question_id=None, **delivery):  # noqa: ANN001, ANN003, ANN201
        _Repository.deliveries.append(delivery)
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
    _Repository.deliveries = []
    monkeypatch.setattr(classroom_module, "SessionRepository", _Repository)


def _room(
    interval: float = 3600.0,
    window: float = 30.0,
    prompts: int = 3,
    prompt_ttl: float = 60.0,
    missed: int = 0,
    interval_max: float | None = None,
    rng: object | None = None,
    production: bool = False,
) -> tuple[Classroom, SessionHub]:
    """interval alone fixes the wait between questions, so timing tests are
    exact; interval_max makes it the random range the cycle draws from."""
    events = SessionHub()
    settings = SimpleNamespace(
        checkpoint_interval_min_seconds=interval,
        checkpoint_interval_max_seconds=interval if interval_max is None else interval_max,
        checkpoint_response_window_seconds=window,
        dynamic_prompt_max_per_student=prompts,
        attention_prompt_ttl_seconds=prompt_ttl,
        attention_prompt_after_missed_questions=missed,
        is_production=production,
        comprehension_alert_threshold=0.5,
        comprehension_alert_min_respondents=5,
    )
    room = Classroom(
        events=events,
        sessions=lambda: _Db,
        settings=lambda: settings,
        rng=rng,  # type: ignore[arg-type]
    )
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


async def test_the_delivery_is_recorded_with_the_window_the_class_is_shown() -> None:
    """The delivery row and question.delivered are given one closes_at,
    computed once, so the store and the class agree on when the window shut."""
    room, events = _room(window=30)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)

    await _deliver(room, row)

    [delivery] = _Repository.deliveries
    [shown] = socket.of(ServerEventType.QUESTION_DELIVERED)
    assert delivery["window_seconds"] == shown["data"]["window_seconds"] == 30
    assert delivery["closes_at"] == datetime.fromisoformat(shown["data"]["closes_at"])
    assert delivery["closes_at"] - delivery["delivered_at"] == timedelta(seconds=30)
    await room.shutdown()


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
    live.open.question.closes_at = datetime.now(UTC) - timedelta(milliseconds=1)

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


async def test_feedback_follows_the_receipt_and_reaches_only_that_student() -> None:
    """A recorder that sent feedback itself could show "Correct" for an
    answer the classroom then refused. What it returns goes out after the
    receipt instead, to the student who answered and nobody else."""
    room, events = _room()
    row = _row()
    answering, student = await _join(events, row.session_id, Role.STUDENT)
    other, _ = await _join(events, row.session_id, Role.STUDENT)
    lecturer, _ = await _join(events, row.session_id, Role.LECTURER)
    question = await _deliver(room, row)

    class Recorder:
        async def record(self, submission: Submission) -> FeedbackResultPayload:
            assert answering.of(ServerEventType.ANSWER_RECEIPT) == []
            return FeedbackResultPayload(question_id=submission.question_id, correct=True)

    room.recorder = Recorder()
    await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))

    receipt, feedback = answering.sent[-2:]
    assert (receipt["type"], receipt["data"]["accepted"]) == ("answer.receipt", True)
    assert (feedback["type"], feedback["data"]["correct"]) == ("feedback.result", True)
    for socket in (other, lecturer):
        assert socket.of(ServerEventType.FEEDBACK_RESULT) == []
        assert socket.of(ServerEventType.ANSWER_RECEIPT) == []
    await room.shutdown()


async def test_a_refused_answer_gets_a_receipt_and_no_feedback() -> None:
    room, events = _room()
    row = _row()
    socket, student = await _join(events, row.session_id, Role.STUDENT)
    question = await _deliver(room, row)

    class Recorder:
        async def record(self, submission: Submission) -> FeedbackResultPayload:
            raise RuntimeError("database gone")

    room.recorder = Recorder()
    await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))

    [receipt] = socket.of(ServerEventType.ANSWER_RECEIPT)
    assert receipt["data"]["accepted"] is False
    assert socket.of(ServerEventType.FEEDBACK_RESULT) == []
    await room.shutdown()


class _Closes:
    def __init__(self) -> None:
        self.closed: list[ClosedQuestion] = []
        self.release = asyncio.Event()
        self.release.set()

    async def record_close(self, closed: ClosedQuestion) -> None:
        await self.release.wait()
        self.closed.append(closed)


async def test_the_close_recorder_is_told_who_was_shown_and_who_answered() -> None:
    room, events = _room(window=0.1)
    row = _row()
    socket, answered = await _join(events, row.session_id, Role.STUDENT)
    _, silent = await _join(events, row.session_id, Role.STUDENT)
    closes = room.close_recorder = _Closes()
    question = await _deliver(room, row)
    await room.submit(row.session_id, answered, Role.STUDENT, _answer(question.question_id))

    await asyncio.sleep(0.25)

    [closed] = closes.closed
    assert (closed.question_id, closed.reason) == (question.question_id, "window_elapsed")
    assert closed.eligible == {answered, silent}
    assert closed.answered == {answered}
    assert socket.of(ServerEventType.QUESTION_CLOSED)
    await room.shutdown()


async def test_the_close_recorder_hears_about_a_question_the_end_closed() -> None:
    room, _ = _room()
    row = _row()
    closes = room.close_recorder = _Closes()
    question = await _deliver(room, row)

    await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    [closed] = closes.closed
    assert (closed.question_id, closed.reason) == (question.question_id, "session_ended")


async def test_a_slow_close_recorder_does_not_hold_up_the_session() -> None:
    """It runs once the session's lock is released, so the next question can
    go out while the last close is still being stored."""
    room, _ = _room(window=0.05)
    row = _row()
    closes = room.close_recorder = _Closes()
    closes.release.clear()
    await _deliver(room, row)
    await asyncio.sleep(0.15)

    await asyncio.wait_for(_deliver(room, row), 1)

    assert closes.closed == []
    closes.release.set()
    await room.shutdown()


async def test_a_failing_close_recorder_is_logged_and_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, _ = _room(window=0.05)
    row = _row()

    class Broken:
        async def record_close(self, closed: ClosedQuestion) -> None:
            raise RuntimeError("database gone")

    room.close_recorder = Broken()
    await _deliver(room, row)
    with caplog.at_level("ERROR", logger="clip.classroom"):
        await asyncio.sleep(0.15)

    assert "could not record a question close" in caplog.text
    await _deliver(room, row)
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


async def test_a_manual_question_discards_what_was_due() -> None:
    """The cycle was due 0.1s after the lecturer's question. Instead the next
    wait starts when that question closes, 0.05s after it went out."""
    room, events = _room(interval=0.3, window=0.05)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    room.activate(row.session_id)
    await asyncio.sleep(0.2)
    await _deliver(room, row)
    _Repository.staged.append(_Question())

    await asyncio.sleep(0.2)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await asyncio.sleep(0.25)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 2
    await room.shutdown()


async def test_the_next_wait_starts_when_the_question_closes() -> None:
    """Delivered at 0.2s and closed at 0.35s, the next is due at 0.55s. Counted
    from the delivery it would have gone out at 0.4s, taking the response
    window out of the teaching time."""
    room, events = _room(interval=0.2, window=0.15)
    row = _row()
    socket, _ = await _join(events, row.session_id, Role.STUDENT)
    _Repository.staged.extend([_Question(), _Question()])

    room.activate(row.session_id)
    await asyncio.sleep(0.47)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await asyncio.sleep(0.18)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 2
    await room.shutdown()


class _Draws:
    """Stands in for random.Random: records each range and returns a chosen
    point in it, so the test knows every wait the cycle drew."""

    def __init__(self, *fractions: float) -> None:
        self.fractions = list(fractions)
        self.ranges: list[tuple[float, float]] = []

    def uniform(self, low: float, high: float) -> float:
        self.ranges.append((low, high))
        return low + (high - low) * self.fractions.pop(0)


async def test_each_wait_is_drawn_fresh_from_the_configured_range() -> None:
    draws = _Draws(0.0, 1.0, 0.5)
    room, _ = _room(interval=900, interval_max=1200, window=0.05, rng=draws)
    row = _row()

    live = room.activate(row.session_id)
    first = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
    await _deliver(room, row)
    await asyncio.sleep(0.1)
    second = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
    await _deliver(room, row)
    await asyncio.sleep(0.1)
    third = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]

    assert draws.ranges == [(900, 1200)] * 3
    assert 899 < first <= 900
    assert 1199 < second <= 1200
    assert 1049 < third <= 1050
    await room.shutdown()


async def test_nothing_is_due_while_a_question_is_open() -> None:
    room, _ = _room(window=30)
    row = _row()
    live = room.activate(row.session_id)
    assert live.countdown.due is not None

    await _deliver(room, row)

    assert live.countdown.due is None
    await room.shutdown()


async def test_pausing_mid_question_draws_the_wait_at_its_close_and_uses_it_on_resume() -> None:
    room, _ = _room(interval=10, window=0.05)
    row = _row()
    live = room.activate(row.session_id)
    await _deliver(room, row)

    await room.pause(_Db(), row)  # type: ignore[arg-type]
    await asyncio.sleep(0.1)  # the question closes while paused
    assert live.countdown.due is None and live.countdown.left == timedelta(seconds=10)
    await room.resume(_Db(), row)  # type: ignore[arg-type]

    left = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
    assert 9 < left <= 10
    await room.shutdown()


async def test_resuming_while_a_question_is_still_open_waits_for_its_close() -> None:
    room, _ = _room(interval=10, window=30)
    row = _row()
    live = room.activate(row.session_id)
    await _deliver(room, row)

    await room.pause(_Db(), row)  # type: ignore[arg-type]
    await room.resume(_Db(), row)  # type: ignore[arg-type]

    assert live.countdown.due is None
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

    async def flaky(self, live, question_id=None, **delivery):  # noqa: ANN001, ANN003, ANN202
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database hiccup")
        return await real_claim(self, live, question_id, **delivery)

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
    live.countdown.due = datetime.now(UTC) + timedelta(seconds=4)

    await room.pause(_Db(), row)  # type: ignore[arg-type]
    await room.resume(_Db(), row)  # type: ignore[arg-type]

    left = (live.countdown.due - datetime.now(UTC)).total_seconds()
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

    assert live is not None and live.countdown.paused and live.cycle is None
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


# -- the scheduler's own triggers ---------------------------------------------


async def _let_pass(room: Classroom, row: SimpleNamespace) -> _Question:
    question = await _deliver(room, row)
    await asyncio.sleep(0.1)
    return question


async def test_a_student_who_lets_two_questions_pass_is_nudged() -> None:
    room, events = _room(window=0.05, missed=2)
    row = _row()
    room.activate(row.session_id)
    quiet, _ = await _join(events, row.session_id, Role.STUDENT)
    lecturer, _ = await _join(events, row.session_id, Role.LECTURER)

    await _let_pass(room, row)
    assert quiet.of(ServerEventType.PROMPT_ATTENTION) == []
    await _let_pass(room, row)

    [prompt] = quiet.of(ServerEventType.PROMPT_ATTENTION)
    assert (prompt["seq"], prompt["data"]["escalation"]) == (0, 1)
    assert "missed the last 2 questions" in prompt["data"]["message"]
    assert lecturer.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_answering_resets_the_count_of_missed_questions() -> None:
    room, events = _room(window=0.05, missed=2)
    row = _row()
    room.activate(row.session_id)
    socket, student = await _join(events, row.session_id, Role.STUDENT)

    await _let_pass(room, row)
    question = await _deliver(room, row)
    await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))
    await asyncio.sleep(0.1)
    await _let_pass(room, row)

    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_missed_question_nudges_can_be_turned_off() -> None:
    room, events = _room(window=0.05, missed=0)
    row = _row()
    room.activate(row.session_id)
    socket, _ = await _join(events, row.session_id, Role.STUDENT)

    for _ in range(3):
        await _let_pass(room, row)

    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_an_empty_queue_is_logged_not_shown_and_tried_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, events = _room(interval=0.1, window=0.05)
    row = _row()
    lecturer, _ = await _join(events, row.session_id, Role.LECTURER)
    student, _ = await _join(events, row.session_id, Role.STUDENT)

    with caplog.at_level("INFO", logger="clip.classroom"):
        room.activate(row.session_id)
        await asyncio.sleep(0.15)
    assert "No static question available" in caplog.text
    assert lecturer.sent == student.sent == []

    _Repository.staged.append(_Question())
    await asyncio.sleep(0.12)
    assert len(student.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await room.shutdown()


class _Attendance:
    def __init__(self) -> None:
        self.joined: list[Attendance] = []
        self.left: list[Attendance] = []

    async def record_join(self, joined: Attendance) -> None:
        self.joined.append(joined)

    async def record_leave(self, left: Attendance) -> None:
        self.left.append(left)


async def _tab(events: SessionHub, session_id: UUID, user: UUID, role: Role) -> Connection:
    connection = Connection(_Socket(), user, session_id, role)  # type: ignore[arg-type]
    await events.join(connection)
    return connection


async def test_a_student_leaves_the_class_only_when_their_last_tab_closes() -> None:
    """The stored record counts joins, not open sockets, so it cannot tell a
    student who closed one of two tabs from one who left."""
    room, events = _room()
    row = _row()
    attendance = room.participant_recorder = _Attendance()
    student = uuid4()
    tabs = []
    for _ in range(2):
        tabs.append(await _tab(events, row.session_id, student, Role.STUDENT))
        await room.arrived(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert [a.user_id for a in attendance.joined] == [student, student]

    await events.leave(tabs[0])
    await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert attendance.left == []

    await events.leave(tabs[1])
    await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert [a.user_id for a in attendance.left] == [student]
    await room.shutdown()


async def test_staff_are_told_when_a_student_arrives_or_leaves_but_not_about_a_second_tab() -> None:
    """Presence changes with the student, not the socket: a second tab is
    attendance, and says nothing new about who is in the room."""
    room, events = _room()
    row = _row()
    lecturer, _ = await _join(events, row.session_id, Role.LECTURER)
    student = uuid4()
    tabs = []
    for _ in range(2):
        tabs.append(await _tab(events, row.session_id, student, Role.STUDENT))
        await room.arrived(row.session_id, student, Role.STUDENT, SessionStatus.PREPARED)
    for tab in tabs:
        await events.leave(tab)
        await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.PREPARED)

    counts = [e["data"]["participant_count"] for e in lecturer.of(ServerEventType.SESSION_STATE)]
    assert counts == [1, 0]
    await room.shutdown()


async def test_staff_are_not_participants() -> None:
    """A lecturer is in the room without attending it, and the store keeps
    participants by student, which they have no row in."""
    room, events = _room()
    row = _row()
    attendance = room.participant_recorder = _Attendance()
    lecturer = uuid4()
    tab = await _tab(events, row.session_id, lecturer, Role.LECTURER)

    await room.arrived(row.session_id, lecturer, Role.LECTURER, SessionStatus.ACTIVE)
    await events.leave(tab)
    await room.departed(row.session_id, lecturer, Role.LECTURER, SessionStatus.ACTIVE)

    assert (attendance.joined, attendance.left) == ([], [])
    await room.shutdown()


async def test_a_failing_participant_recorder_is_logged_and_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, events = _room()
    row = _row()

    class Broken:
        async def record_join(self, joined: Attendance) -> None:
            raise RuntimeError("database gone")

        async def record_leave(self, left: Attendance) -> None:
            raise RuntimeError("database gone")

    room.participant_recorder = Broken()
    student = uuid4()
    tab = await _tab(events, row.session_id, student, Role.STUDENT)

    with caplog.at_level("ERROR", logger="clip.classroom"):
        await room.arrived(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)
        await events.leave(tab)
        await room.departed(row.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    assert "could not record a student joining" in caplog.text
    assert "could not record a student leaving" in caplog.text
    await room.shutdown()


# -- startup wiring -------------------------------------------------------------


class _Recorder:
    async def record(self, submission: Submission) -> None:
        return None

    async def record_prompt(self, outcome) -> None:  # noqa: ANN001
        return None

    async def record_close(self, closed) -> None:  # noqa: ANN001
        return None

    async def record_join(self, joined) -> None:  # noqa: ANN001
        return None

    async def record_leave(self, left) -> None:  # noqa: ANN001
        return None


def _wired(room: Classroom) -> None:
    room.recorder = room.prompt_recorder = room.close_recorder = _Recorder()  # type: ignore[assignment]
    room.participant_recorder = _Recorder()  # type: ignore[assignment]


def test_development_is_told_what_live_sessions_will_not_store(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    room, _ = _room()

    with caplog.at_level("WARNING", logger="clip.classroom"):
        room.check_wiring()

    assert "answers are not stored" in caplog.text
    assert "prompt outcomes are not stored" in caplog.text
    assert "question closes are not stored" in caplog.text
    assert "who attended is not stored" in caplog.text


def test_production_will_not_start_without_somewhere_to_store_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    room, _ = _room(production=True)

    with pytest.raises(RuntimeError, match="answers are not stored"):
        room.check_wiring()

    _wired(room)
    room.check_wiring()


@pytest.mark.parametrize("workers", ["2", "4", "auto"])
def test_live_sessions_refuse_more_than_one_worker(
    monkeypatch: pytest.MonkeyPatch, workers: str
) -> None:
    """Each worker would restore the same session and run its own cycle."""
    monkeypatch.setenv("WEB_CONCURRENCY", workers)
    room, _ = _room(production=True)
    _wired(room)

    with pytest.raises(RuntimeError, match="single worker"):
        room.check_wiring()


def test_one_worker_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    room, _ = _room(production=True)
    _wired(room)

    room.check_wiring()


async def test_how_a_question_is_answered_comes_from_its_type() -> None:
    """A multiple choice question whose choices went missing was delivered as
    a free-text one: the student saw buttons and was told to answer in their
    own words. The stored type decides, and disagreeing options are dropped."""
    room, events = _room()
    row = _row()
    socket, student = await _join(events, row.session_id, Role.STUDENT)
    _Repository.staged.append(_Question(question_type="free_text", options=["Mars", "Venus"]))

    delivered = await room.deliver(_Db(), row)  # type: ignore[arg-type]

    assert delivered is not None and delivered.options is None
    [event] = socket.of(ServerEventType.QUESTION_DELIVERED)
    assert event["data"]["options"] is None
    chosen = await room.submit(
        row.session_id, student, Role.STUDENT, _answer(delivered.question_id, option=0)
    )
    written = await room.submit(
        row.session_id, student, Role.STUDENT, _answer(delivered.question_id, None, "Jupiter")
    )
    assert not chosen.accepted and chosen.reason == "Answer this question in your own words."
    assert written.accepted
    await room.shutdown()


# -- engagement scoring and comprehension alerts (Cyber 1) --------------------


async def _close(room: Classroom, row: SimpleNamespace, answer: UUID | None = None) -> None:
    question = await _deliver(room, row)
    if answer is not None:
        receipt = await room.submit(
            row.session_id, answer, Role.STUDENT, _answer(question.question_id)
        )
        assert receipt.accepted
    await asyncio.sleep(0.15)


async def test_a_late_joiner_who_has_not_answered_is_not_nudged_by_engagement() -> None:
    room, _, row, socket, student, _ = await _prompted_room(window=0.05, missed=0)

    await _close(room, row)
    await _close(room, row)
    await _close(room, row)

    # Three questions missed, but the attempt rate is the only evidence, so
    # engagement scoring stays quiet. It still reports the student.
    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    [scored] = room.engagement(row.session_id)
    assert (scored.user_id, scored.engagement.status.value) == (student, "at_risk")
    assert scored.engagement.signals_available == ["attempt_rate"]
    await room.shutdown()


async def test_engagement_nudges_once_a_second_signal_agrees() -> None:
    room, _, row, socket, student, _ = await _prompted_room(window=0.05, prompt_ttl=0.05, missed=0)
    assert await room.prompt_student(row.session_id, student, "Still with us?")
    await asyncio.sleep(0.1)  # the prompt expires unanswered

    await _close(room, row)
    await _close(room, row)

    prompts = socket.of(ServerEventType.PROMPT_ATTENTION)
    assert prompts[-1]["data"]["message"] == classroom_module.ENGAGEMENT_PROMPT_MESSAGE
    [scored] = room.engagement(row.session_id)
    assert scored.engagement.status.value == "disengaged"
    assert scored.engagement.signals_available == ["attempt_rate", "prompt_response"]
    await room.shutdown()


async def test_an_answering_student_is_scored_engaged() -> None:
    room, _, row, socket, student, _ = await _prompted_room(window=0.2, missed=0)

    await _close(room, row, answer=student)
    await asyncio.sleep(0.15)

    [scored] = room.engagement(row.session_id)
    assert scored.engagement.status.value == "engaged"
    assert scored.engagement.signals_available == ["response_timing"]
    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_an_attention_signal_is_kept_only_for_a_connected_student() -> None:
    room, events, row, _, student, _ = await _prompted_room(window=0.05, missed=0)
    _, lecturer = await _join(events, row.session_id, Role.LECTURER)
    signal = AttentionSignalPayload(gaze_on_screen_ratio=0.8, window_seconds=5.0)

    assert await room.record_attention(row.session_id, student, signal)
    assert not await room.record_attention(row.session_id, lecturer, signal)
    assert not await room.record_attention(uuid4(), student, signal)

    await _close(room, row)
    [scored] = room.engagement(row.session_id)
    assert scored.engagement.signals_available == ["gaze"]
    await room.shutdown()


@dataclass
class _Labels:
    labels: list[str]
    topic: str | None = "Planets"
    asked: list = field(default_factory=list)

    async def question_labels(self, session_id: UUID, question_id: UUID):  # noqa: ANN201
        self.asked.append((session_id, question_id))
        return QuestionComprehension(labels=self.labels, topic=self.topic)


async def test_a_struggling_class_raises_an_alert_to_the_lecturer_only() -> None:
    room, events, row, student_socket, _, _ = await _prompted_room(window=0.05, missed=0)
    lecturer_socket, _ = await _join(events, row.session_id, Role.LECTURER)
    room.comprehension_source = _Labels(["struggling"] * 3 + ["partial"] + ["mastered"] * 2)

    await _close(room, row)

    [alert] = lecturer_socket.of(ServerEventType.ALERT_RAISED)
    assert alert["data"]["kind"] == "topic_difficulty"
    assert "Planets" in alert["data"]["message"]
    assert alert["data"]["reason"] == "4 of 6 classified answers were partial or struggling."
    assert student_socket.of(ServerEventType.ALERT_RAISED) == []
    [stored] = room.alerts(row.session_id)
    assert (stored.respondents, stored.threshold) == (6, 0.5)
    assert stored.correct_ratio == 2 / 6
    await room.shutdown()


async def test_too_few_classified_answers_raise_no_alert() -> None:
    room, events, row, _, _, _ = await _prompted_room(window=0.05, missed=0)
    lecturer_socket, _ = await _join(events, row.session_id, Role.LECTURER)
    room.comprehension_source = _Labels(["struggling"] * 4)

    await _close(room, row)

    assert lecturer_socket.of(ServerEventType.ALERT_RAISED) == []
    assert room.alerts(row.session_id) == []
    await room.shutdown()


async def test_a_stale_attention_signal_no_longer_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attention_module, "ATTENTION_SIGNAL_MAX_AGE_SECONDS", 0.05)
    room, _, row, _, student, _ = await _prompted_room(window=0.05, missed=0)
    signal = AttentionSignalPayload(gaze_on_screen_ratio=0.8, window_seconds=5.0)
    assert await room.record_attention(row.session_id, student, signal)
    await asyncio.sleep(0.1)

    await _close(room, row)

    [scored] = room.engagement(row.session_id)
    assert "gaze" not in scored.engagement.signals_available
    await room.shutdown()


async def test_ending_the_class_still_counts_the_last_question() -> None:
    room, events, row, socket, student, _ = await _prompted_room(window=30, missed=0)
    lecturer_socket, _ = await _join(events, row.session_id, Role.LECTURER)
    labels = _Labels(["struggling"] * 5 + ["mastered"])
    room.comprehension_source = labels
    question = await _deliver(room, row)
    assert (
        await room.submit(row.session_id, student, Role.STUDENT, _answer(question.question_id))
    ).accepted
    scores: list = []
    attention = room.get_running(row.session_id).attention  # type: ignore[union-attr]
    real_score = attention.score

    def spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        scored = real_score(*args, **kwargs)
        scores.extend(s.engagement for s in scored)
        return scored

    attention.score = spy  # type: ignore[method-assign]

    await room.end(row.session_id, SessionStatus.ENDED, 1)

    [engagement] = scores
    assert engagement.signals_available == ["response_timing"]
    assert labels.asked == [(row.session_id, question.question_id)]
    [alert] = lecturer_socket.of(ServerEventType.ALERT_RAISED)
    assert alert["data"]["kind"] == "topic_difficulty"
    # Nobody is nudged in a class that has ended.
    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
