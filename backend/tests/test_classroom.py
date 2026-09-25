"""The running side of a live session: delivery, the response window, answers
and the question cycle.

Owner: General CS. The database is replaced by a fake repository so these
exercise the timing and the rules alone; test_session_lifecycle.py covers the
routes against a real database. Recording and attention have files of their
own.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.errors import ConflictError
from app.realtime import classroom as classroom_module
from app.realtime.recorders import (
    Submission,
)
from app.schemas.events import (
    FeedbackResultPayload,
    ServerEventType,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus

from .classroom_support import (
    FakeDb,
    FakeRepository,
    StagedQuestion,
    answer_to,
    deliver_next,
    join_as,
    make_room,
    make_row,
)

pytestmark = pytest.mark.usefixtures("fake_session_repository")


async def test_the_delivery_is_recorded_with_the_window_the_class_is_shown() -> None:
    """The delivery row and question.delivered are given one closes_at,
    computed once, so the store and the class agree on when the window shut."""
    room, events = make_room(window=30)
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)

    await deliver_next(room, row)

    [delivery] = FakeRepository.deliveries
    [shown] = socket.of(ServerEventType.QUESTION_DELIVERED)
    assert delivery["window_seconds"] == shown["data"]["window_seconds"] == 30
    assert delivery["closes_at"] == datetime.fromisoformat(shown["data"]["closes_at"])
    assert delivery["closes_at"] - delivery["delivered_at"] == timedelta(seconds=30)
    await room.shutdown()


async def test_a_delivered_question_reaches_everyone_without_its_answer() -> None:
    room, events = make_room(window=30)
    row = make_row()
    student, _ = await join_as(events, row.session_id, Role.STUDENT)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)

    question = await deliver_next(room, row)

    for socket in (student, lecturer):
        [event] = socket.of(ServerEventType.QUESTION_DELIVERED)
        assert event["data"]["question_id"] == str(question.question_id)
        assert event["data"]["options"] == question.options
        assert event["data"]["window_seconds"] == 30
        assert "correct_option" not in event["data"]
    await room.shutdown()


async def test_the_delivery_is_recorded_before_anyone_is_told() -> None:
    room, events = make_room()
    row = make_row()
    db = FakeDb()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)

    async def commit() -> None:
        assert socket.of(ServerEventType.QUESTION_DELIVERED) == []
        db.commits += 1

    db.commit = commit  # type: ignore[method-assign]
    FakeRepository.staged.append(StagedQuestion())
    await room.deliver(db, row)  # type: ignore[arg-type]

    assert db.commits == 1
    assert socket.of(ServerEventType.QUESTION_DELIVERED)
    await room.shutdown()


async def test_a_second_question_is_refused_while_one_is_open() -> None:
    room, _ = make_room()
    row = make_row()
    await deliver_next(room, row)
    FakeRepository.staged.append(StagedQuestion())

    with pytest.raises(ConflictError):
        await room.deliver(FakeDb(), row)  # type: ignore[arg-type]
    await room.shutdown()


async def test_nothing_staged_delivers_nothing() -> None:
    room, events = make_room()
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)

    assert await room.deliver(FakeDb(), row) is None  # type: ignore[arg-type]
    assert socket.sent == []
    await room.shutdown()


async def test_the_window_closes_itself_and_reports_who_answered() -> None:
    room, events = make_room(window=0.2)
    row = make_row()
    watcher, _ = await join_as(events, row.session_id, Role.LECTURER)
    _, answering = await join_as(events, row.session_id, Role.STUDENT)
    await join_as(events, row.session_id, Role.STUDENT)
    question = await deliver_next(room, row)

    receipt = await room.submit(
        row.session_id, answering, Role.STUDENT, answer_to(question.question_id)
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
    room, events = make_room(window=0.2)
    row = make_row()
    watcher, _ = await join_as(events, row.session_id, Role.LECTURER)
    question = await deliver_next(room, row)
    _, late = await join_as(events, row.session_id, Role.STUDENT)

    assert (
        await room.submit(row.session_id, late, Role.STUDENT, answer_to(question.question_id))
    ).accepted
    await asyncio.sleep(0.4)

    [closed] = watcher.of(ServerEventType.QUESTION_CLOSED)
    assert (closed["data"]["respondents"], closed["data"]["eligible"]) == (1, 1)
    await room.shutdown()


async def test_the_next_question_can_go_out_once_the_window_has_closed() -> None:
    room, _ = make_room(window=0.1)
    row = make_row()
    await deliver_next(room, row)
    await asyncio.sleep(0.25)

    await deliver_next(room, row)
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
    room, _ = make_room()
    row = make_row()
    question = await deliver_next(room, row)
    target = uuid4() if answer.pop("other_question", False) else question.question_id

    receipt = await room.submit(row.session_id, uuid4(), role, answer_to(target, **answer))

    assert (receipt.accepted, receipt.reason) == (False, reason)
    await room.shutdown()


async def test_a_student_answers_each_question_once() -> None:
    room, _ = make_room()
    row = make_row()
    question = await deliver_next(room, row)
    student = uuid4()

    first = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(question.question_id)
    )
    second = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(question.question_id, 0)
    )

    assert first.accepted
    assert (second.accepted, second.reason) == (False, "You have already answered this question.")
    await room.shutdown()


async def test_an_answer_after_the_window_is_refused_even_before_it_is_closed() -> None:
    """The close runs on a timer that can fire late. The deadline is closes_at,
    not whenever the timer gets round to it."""
    room, _ = make_room()
    row = make_row()
    question = await deliver_next(room, row)
    live = room._live[row.session_id]
    assert live.open is not None
    live.open.question.closes_at = datetime.now(UTC) - timedelta(milliseconds=1)

    receipt = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, answer_to(question.question_id)
    )

    assert (receipt.accepted, receipt.reason) == (False, "The response window has closed.")
    await room.shutdown()


async def test_a_free_text_question_takes_words_not_an_option() -> None:
    room, _ = make_room()
    row = make_row()
    question = StagedQuestion(options=None, correct_option=None)
    FakeRepository.staged.append(question)
    await room.deliver(FakeDb(), row)  # type: ignore[arg-type]

    by_option = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, answer_to(question.question_id)
    )
    in_words = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, answer_to(question.question_id, None, "Jupiter")
    )

    assert (by_option.accepted, by_option.reason) == (
        False,
        "Answer this question in your own words.",
    )
    assert in_words.accepted
    await room.shutdown()


async def test_the_recorder_receives_each_accepted_answer() -> None:
    room, _ = make_room()
    recorded: list[Submission] = []

    class Recorder:
        async def record(self, submission: Submission) -> None:
            recorded.append(submission)

    room.recorder = Recorder()
    row = make_row()
    question = await deliver_next(room, row)
    student = uuid4()

    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id, 2))

    [submission] = recorded
    assert (submission.user_id, submission.selected_option, submission.client_elapsed_ms) == (
        student,
        2,
        900,
    )
    await room.shutdown()


async def test_an_answer_that_could_not_be_saved_can_be_sent_again() -> None:
    room, _ = make_room()
    failures = [RuntimeError("database gone")]

    class Recorder:
        async def record(self, submission: Submission) -> None:
            if failures:
                raise failures.pop()

    room.recorder = Recorder()
    row = make_row()
    question = await deliver_next(room, row)
    student = uuid4()

    first = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(question.question_id)
    )
    retry = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(question.question_id)
    )

    assert not first.accepted
    assert "could not be saved" in (first.reason or "")
    assert retry.accepted
    await room.shutdown()


async def test_feedback_follows_the_receipt_and_reaches_only_that_student() -> None:
    """A recorder that sent feedback itself could show "Correct" for an
    answer the classroom then refused. What it returns goes out after the
    receipt instead, to the student who answered and nobody else."""
    room, events = make_room()
    row = make_row()
    answering, student = await join_as(events, row.session_id, Role.STUDENT)
    other, _ = await join_as(events, row.session_id, Role.STUDENT)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    question = await deliver_next(room, row)

    class Recorder:
        async def record(self, submission: Submission) -> FeedbackResultPayload:
            assert answering.of(ServerEventType.ANSWER_RECEIPT) == []
            return FeedbackResultPayload(question_id=submission.question_id, correct=True)

    room.recorder = Recorder()
    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))

    receipt, feedback = answering.sent[-2:]
    assert (receipt["type"], receipt["data"]["accepted"]) == ("answer.receipt", True)
    assert (feedback["type"], feedback["data"]["correct"]) == ("feedback.result", True)
    for socket in (other, lecturer):
        assert socket.of(ServerEventType.FEEDBACK_RESULT) == []
        assert socket.of(ServerEventType.ANSWER_RECEIPT) == []
    await room.shutdown()


async def test_a_refused_answer_gets_a_receipt_and_no_feedback() -> None:
    room, events = make_room()
    row = make_row()
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    question = await deliver_next(room, row)

    class Recorder:
        async def record(self, submission: Submission) -> FeedbackResultPayload:
            raise RuntimeError("database gone")

    room.recorder = Recorder()
    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))

    [receipt] = socket.of(ServerEventType.ANSWER_RECEIPT)
    assert receipt["data"]["accepted"] is False
    assert socket.of(ServerEventType.FEEDBACK_RESULT) == []
    await room.shutdown()


async def test_ending_closes_the_open_question_then_announces_the_end() -> None:
    room, events = make_room()
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    question = await deliver_next(room, row)

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
    room, _ = make_room()
    row = make_row()
    question = await deliver_next(room, row)
    await room.end(row.session_id, SessionStatus.ENDED, delivered=1)

    receipt = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, answer_to(question.question_id)
    )

    assert not receipt.accepted


async def test_the_cycle_delivers_the_next_question_on_its_own() -> None:
    room, events = make_room(interval=0.15, window=0.05)
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    FakeRepository.staged.extend([StagedQuestion(), StagedQuestion()])

    room.activate(row.session_id)
    await asyncio.sleep(0.5)

    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 2
    assert len(socket.of(ServerEventType.QUESTION_CLOSED)) == 2
    await room.shutdown()


async def test_a_manual_question_discards_what_was_due() -> None:
    """The cycle was due 0.1s after the lecturer's question. Instead the next
    wait starts when that question closes, 0.05s after it went out."""
    room, events = make_room(interval=0.3, window=0.05)
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    room.activate(row.session_id)
    await asyncio.sleep(0.2)
    await deliver_next(room, row)
    FakeRepository.staged.append(StagedQuestion())

    await asyncio.sleep(0.2)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await asyncio.sleep(0.25)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 2
    await room.shutdown()


async def test_the_next_wait_starts_when_the_question_closes() -> None:
    """Delivered at 0.2s and closed at 0.35s, the next is due at 0.55s. Counted
    from the delivery it would have gone out at 0.4s, taking the response
    window out of the teaching time."""
    room, events = make_room(interval=0.2, window=0.15)
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    FakeRepository.staged.extend([StagedQuestion(), StagedQuestion()])

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
    room, _ = make_room(interval=900, interval_max=1200, window=0.05, rng=draws)
    row = make_row()

    live = room.activate(row.session_id)
    first = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
    await deliver_next(room, row)
    await asyncio.sleep(0.1)
    second = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
    await deliver_next(room, row)
    await asyncio.sleep(0.1)
    third = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]

    assert draws.ranges == [(900, 1200)] * 3
    assert 899 < first <= 900
    assert 1199 < second <= 1200
    assert 1049 < third <= 1050
    await room.shutdown()


async def test_nothing_is_due_while_a_question_is_open() -> None:
    room, _ = make_room(window=30)
    row = make_row()
    live = room.activate(row.session_id)
    assert live.countdown.due is not None

    await deliver_next(room, row)

    assert live.countdown.due is None
    await room.shutdown()


async def test_pausing_mid_question_draws_the_wait_at_its_close_and_uses_it_on_resume() -> None:
    room, _ = make_room(interval=10, window=0.05)
    row = make_row()
    live = room.activate(row.session_id)
    await deliver_next(room, row)

    await room.pause(FakeDb(), row)  # type: ignore[arg-type]
    await asyncio.sleep(0.1)  # the question closes while paused
    assert live.countdown.due is None and live.countdown.left == timedelta(seconds=10)
    await room.resume(FakeDb(), row)  # type: ignore[arg-type]

    left = (live.countdown.due - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
    assert 9 < left <= 10
    await room.shutdown()


async def test_resuming_while_a_question_is_still_open_waits_for_its_close() -> None:
    room, _ = make_room(interval=10, window=30)
    row = make_row()
    live = room.activate(row.session_id)
    await deliver_next(room, row)

    await room.pause(FakeDb(), row)  # type: ignore[arg-type]
    await room.resume(FakeDb(), row)  # type: ignore[arg-type]

    assert live.countdown.due is None
    await room.shutdown()


async def test_the_cycle_stops_once_the_session_is_no_longer_active() -> None:
    room, _ = make_room(interval=0.05)
    row = make_row()
    live = room.activate(row.session_id)
    row.status = SessionStatus.ENDED.value

    await asyncio.sleep(0.2)

    assert live.cycle is not None and live.cycle.done()
    assert room.get_running(row.session_id) is None


async def test_a_failed_scheduled_delivery_does_not_stop_the_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, events = make_room(interval=0.1, window=0.02)
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    real_claim = FakeRepository.claim_for_delivery
    calls = 0

    async def flaky(self, live, question_id=None, **delivery):  # noqa: ANN001, ANN003, ANN202
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database hiccup")
        return await real_claim(self, live, question_id, **delivery)

    monkeypatch.setattr(FakeRepository, "claim_for_delivery", flaky)
    FakeRepository.staged.append(StagedQuestion())
    room.activate(row.session_id)

    await asyncio.sleep(0.35)

    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await room.shutdown()


async def test_a_joining_client_is_given_the_open_question() -> None:
    room, events = make_room()
    row = make_row()
    question = await deliver_next(room, row)
    answered = uuid4()
    await room.submit(row.session_id, answered, Role.STUDENT, answer_to(question.question_id))

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
    room, _ = make_room()
    started, ended = make_row(), make_row()
    room.activate(started.session_id)

    [(_, now_active)] = room.welcome(started.session_id, SessionStatus.PREPARED, uuid4(), None)
    [(_, now_ended)] = room.welcome(ended.session_id, SessionStatus.ACTIVE, uuid4(), None)

    assert now_active["status"] == "active"
    assert now_ended["status"] == "ended"
    await room.shutdown()


async def test_shutdown_stops_every_timer() -> None:
    room, _ = make_room()
    row = make_row()
    await deliver_next(room, row)
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
    room, _ = make_room()
    row = make_row()
    room.activate(row.session_id)
    stale = SimpleNamespace(**vars(row))

    row.status = SessionStatus.ENDED.value
    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)

    assert await room.restore(FakeDb(), stale) is None  # type: ignore[arg-type]
    assert room.get_running(row.session_id) is None
    [(_, state)] = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.STUDENT)
    assert state["status"] == "ended"


async def test_an_end_while_a_restore_is_reading_the_database_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room, _ = make_room()
    row = make_row()
    reading, release = asyncio.Event(), asyncio.Event()

    async def slow_count(self, session_id: UUID) -> int:  # noqa: ANN001
        reading.set()
        await release.wait()
        return 0

    monkeypatch.setattr(FakeRepository, "count_delivered", slow_count)
    restoring = asyncio.create_task(room.restore(FakeDb(), row))  # type: ignore[arg-type]
    await reading.wait()
    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)
    release.set()

    assert await restoring is None
    assert room.get_running(row.session_id) is None


async def test_a_session_cancelled_after_admission_is_not_reported_as_waiting() -> None:
    room, _ = make_room()
    session_id = uuid4()

    await room.end(session_id, SessionStatus.CANCELLED, delivered=0)

    [(_, state)] = room.welcome(session_id, SessionStatus.PREPARED, uuid4(), Role.STUDENT)
    assert state["status"] == "cancelled"


async def test_a_student_shown_the_question_on_joining_is_eligible_to_answer_it() -> None:
    room, events = make_room(window=0.2)
    row = make_row()
    watcher, _ = await join_as(events, row.session_id, Role.LECTURER)
    await deliver_next(room, row)
    late = uuid4()

    room.welcome(row.session_id, SessionStatus.ACTIVE, late, Role.STUDENT)
    await asyncio.sleep(0.4)

    [closed] = watcher.of(ServerEventType.QUESTION_CLOSED)
    assert (closed["data"]["respondents"], closed["data"]["eligible"]) == (0, 1)
    await room.shutdown()


async def test_participants_are_students_each_counted_once() -> None:
    room, events = make_room()
    row = make_row()
    student = uuid4()
    await join_as(events, row.session_id, Role.STUDENT, student)
    await join_as(events, row.session_id, Role.STUDENT, student)
    await join_as(events, row.session_id, Role.STUDENT)
    await join_as(events, row.session_id, Role.LECTURER)

    assert room.state(row.session_id, SessionStatus.ACTIVE).participant_count == 2


async def test_a_recorder_that_hangs_still_gets_the_student_a_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(classroom_module, "RECORD_TIMEOUT_SECONDS", 0.05)
    room, _ = make_room()

    class Recorder:
        async def record(self, submission: Submission) -> None:
            await asyncio.sleep(10)

    room.recorder = Recorder()
    row = make_row()
    question = await deliver_next(room, row)

    receipt = await asyncio.wait_for(
        room.submit(row.session_id, uuid4(), Role.STUDENT, answer_to(question.question_id)), 1
    )

    assert not receipt.accepted
    assert receipt.reason == "Your answer could not be saved. Please submit it again."
    await room.shutdown()


async def test_a_failed_save_after_the_window_does_not_invite_a_resubmission() -> None:
    room, _ = make_room(window=0.1)

    class Recorder:
        async def record(self, submission: Submission) -> None:
            await asyncio.sleep(0.2)
            raise RuntimeError("database gone")

    room.recorder = Recorder()
    row = make_row()
    question = await deliver_next(room, row)

    receipt = await room.submit(
        row.session_id, uuid4(), Role.STUDENT, answer_to(question.question_id)
    )

    assert receipt.reason == "Your answer could not be saved."
    await room.shutdown()


async def test_an_interval_of_zero_leaves_delivery_to_the_lecturer() -> None:
    room, _ = make_room(interval=0)
    row = make_row()

    live = room.activate(row.session_id)

    assert live.cycle is None
    await deliver_next(room, row)
    await room.shutdown()


# -- pause ------------------------------------------------------------------


async def test_a_paused_session_delivers_nothing_until_it_resumes() -> None:
    room, events = make_room(interval=0.15, window=0.05)
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    FakeRepository.staged.extend([StagedQuestion(), StagedQuestion()])
    cycle = room.activate(row.session_id).cycle

    await room.pause(FakeDb(), row)  # type: ignore[arg-type]
    await asyncio.sleep(0.3)
    # Stopped, not merely refused each time, or resuming would leave two.
    assert cycle is not None and cycle.cancelled()
    assert socket.of(ServerEventType.QUESTION_DELIVERED) == []
    with pytest.raises(ConflictError):
        await room.deliver(FakeDb(), row)  # type: ignore[arg-type]

    await room.resume(FakeDb(), row)  # type: ignore[arg-type]
    await asyncio.sleep(0.25)
    assert len(socket.of(ServerEventType.QUESTION_DELIVERED)) == 1
    states = [e["data"]["paused"] for e in socket.of(ServerEventType.SESSION_STATE)]
    assert states == [True, False]
    await room.shutdown()


async def test_pausing_is_recorded_before_it_is_announced() -> None:
    room, _ = make_room()
    row = make_row()
    room.activate(row.session_id)
    db = FakeDb()

    await room.pause(db, row)  # type: ignore[arg-type]

    assert row.paused_at is not None and db.commits == 1
    await room.resume(db, row)  # type: ignore[arg-type]
    assert row.paused_at is None and db.commits == 2
    await room.shutdown()


async def test_resuming_keeps_the_time_that_was_left() -> None:
    room, _ = make_room(interval=10)
    row = make_row()
    live = room.activate(row.session_id)
    live.countdown.due = datetime.now(UTC) + timedelta(seconds=4)

    await room.pause(FakeDb(), row)  # type: ignore[arg-type]
    await room.resume(FakeDb(), row)  # type: ignore[arg-type]

    left = (live.countdown.due - datetime.now(UTC)).total_seconds()
    assert 3 < left <= 4
    await room.shutdown()


async def test_a_question_open_at_the_pause_runs_to_the_end_of_its_window() -> None:
    room, events = make_room(window=0.2)
    row = make_row()
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    question = await deliver_next(room, row)

    await room.pause(FakeDb(), row)  # type: ignore[arg-type]
    receipt = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(question.question_id)
    )
    await asyncio.sleep(0.35)

    assert receipt.accepted
    [closed] = socket.of(ServerEventType.QUESTION_CLOSED)
    assert closed["data"]["reason"] == "window_elapsed"
    await room.shutdown()


async def test_a_session_paused_before_a_restart_stays_paused() -> None:
    room, _ = make_room(interval=0.05)
    row = make_row()
    row.paused_at = datetime.now(UTC)

    live = await room.restore(FakeDb(), row)  # type: ignore[arg-type]

    assert live is not None and live.countdown.paused and live.cycle is None
    [(_, state)] = room.welcome(row.session_id, SessionStatus.ACTIVE, uuid4(), Role.STUDENT)
    assert state["paused"] is True
    await room.shutdown()


async def test_ending_a_paused_session_reports_it_ended_not_paused() -> None:
    room, events = make_room()
    row = make_row()
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)
    room.activate(row.session_id)
    await room.pause(FakeDb(), row)  # type: ignore[arg-type]

    await room.end(row.session_id, SessionStatus.ENDED, delivered=0)

    state = socket.of(ServerEventType.SESSION_STATE)[-1]["data"]
    assert (state["status"], state["paused"]) == ("ended", False)


async def test_an_empty_queue_is_logged_not_shown_and_tried_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room, events = make_room(interval=0.1, window=0.05)
    row = make_row()
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)
    student, _ = await join_as(events, row.session_id, Role.STUDENT)

    with caplog.at_level("INFO", logger="clip.classroom"):
        room.activate(row.session_id)
        await asyncio.sleep(0.15)
    assert "No static question available" in caplog.text
    assert lecturer.sent == student.sent == []

    FakeRepository.staged.append(StagedQuestion())
    await asyncio.sleep(0.12)
    assert len(student.of(ServerEventType.QUESTION_DELIVERED)) == 1
    await room.shutdown()


async def test_how_a_question_is_answered_comes_from_its_type() -> None:
    """A multiple choice question whose choices went missing was delivered as
    a free-text one: the student saw buttons and was told to answer in their
    own words. The stored type decides, and disagreeing options are dropped."""
    room, events = make_room()
    row = make_row()
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    FakeRepository.staged.append(
        StagedQuestion(question_type="free_text", options=["Mars", "Venus"])
    )

    delivered = await room.deliver(FakeDb(), row)  # type: ignore[arg-type]

    assert delivered is not None and delivered.options is None
    [event] = socket.of(ServerEventType.QUESTION_DELIVERED)
    assert event["data"]["options"] is None
    chosen = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(delivered.question_id, option=0)
    )
    written = await room.submit(
        row.session_id, student, Role.STUDENT, answer_to(delivered.question_id, None, "Jupiter")
    )
    assert not chosen.accepted and chosen.reason == "Answer this question in your own words."
    assert written.accepted
    await room.shutdown()
