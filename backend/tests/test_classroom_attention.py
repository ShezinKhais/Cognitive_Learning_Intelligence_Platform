"""Attention in the classroom: prompts to one student, the nudges the
question cycle triggers, engagement scores and class comprehension alerts.

Owner: General CS, with Cyber 1 for scoring and alerts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.realtime import attention as attention_module
from app.realtime import classroom as classroom_module
from app.realtime.classroom import Classroom
from app.realtime.recorders import (
    QuestionComprehension,
)
from app.schemas.events import (
    AttentionSignalPayload,
    PromptAckPayload,
    ServerEventType,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus

from .classroom_support import (
    FakeDb,
    StagedQuestion,
    answer_to,
    deliver_next,
    join_as,
    make_room,
    make_row,
)

pytestmark = pytest.mark.usefixtures("fake_session_repository")


# -- attention prompts --------------------------------------------------------


@dataclass
class _PromptLog:
    outcomes: list = field(default_factory=list)

    async def record_prompt(self, outcome) -> None:  # noqa: ANN001
        self.outcomes.append(outcome)


async def _prompted_room(**settings: float):  # noqa: ANN202
    room, events = make_room(**settings)  # type: ignore[arg-type]
    row = make_row()
    room.activate(row.session_id)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)
    log = _PromptLog()
    room.prompt_recorder = log
    return room, events, row, socket, student, log


async def test_a_prompt_reaches_only_its_student_outside_the_sequence() -> None:
    room, events, row, socket, student, _ = await _prompted_room()
    classmate, _ = await join_as(events, row.session_id, Role.STUDENT)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)

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
    _, other = await join_as(events, row.session_id, Role.STUDENT)
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
    await deliver_next(room, row)
    assert await room.prompt_student(row.session_id, student, "Answering") is None
    await room.shutdown()


async def test_no_prompt_while_the_session_is_paused() -> None:
    room, _, row, _, student, _ = await _prompted_room()

    await room.pause(FakeDb(), row)  # type: ignore[arg-type]

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


async def _let_pass(room: Classroom, row: SimpleNamespace) -> StagedQuestion:
    question = await deliver_next(room, row)
    await asyncio.sleep(0.1)
    return question


async def test_a_student_who_lets_two_questions_pass_is_nudged() -> None:
    room, events = make_room(window=0.05, missed=2)
    row = make_row()
    room.activate(row.session_id)
    quiet, _ = await join_as(events, row.session_id, Role.STUDENT)
    lecturer, _ = await join_as(events, row.session_id, Role.LECTURER)

    await _let_pass(room, row)
    assert quiet.of(ServerEventType.PROMPT_ATTENTION) == []
    await _let_pass(room, row)

    [prompt] = quiet.of(ServerEventType.PROMPT_ATTENTION)
    assert (prompt["seq"], prompt["data"]["escalation"]) == (0, 1)
    assert "missed the last 2 questions" in prompt["data"]["message"]
    assert lecturer.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_answering_resets_the_count_of_missed_questions() -> None:
    room, events = make_room(window=0.05, missed=2)
    row = make_row()
    room.activate(row.session_id)
    socket, student = await join_as(events, row.session_id, Role.STUDENT)

    await _let_pass(room, row)
    question = await deliver_next(room, row)
    await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))
    await asyncio.sleep(0.1)
    await _let_pass(room, row)

    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


async def test_missed_question_nudges_can_be_turned_off() -> None:
    room, events = make_room(window=0.05, missed=0)
    row = make_row()
    room.activate(row.session_id)
    socket, _ = await join_as(events, row.session_id, Role.STUDENT)

    for _ in range(3):
        await _let_pass(room, row)

    assert socket.of(ServerEventType.PROMPT_ATTENTION) == []
    await room.shutdown()


# -- engagement scoring and comprehension alerts (Cyber 1) --------------------


async def _close(room: Classroom, row: SimpleNamespace, answer: UUID | None = None) -> None:
    question = await deliver_next(room, row)
    if answer is not None:
        receipt = await room.submit(
            row.session_id, answer, Role.STUDENT, answer_to(question.question_id)
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
    _, lecturer = await join_as(events, row.session_id, Role.LECTURER)
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
    lecturer_socket, _ = await join_as(events, row.session_id, Role.LECTURER)
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
    lecturer_socket, _ = await join_as(events, row.session_id, Role.LECTURER)
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
    lecturer_socket, _ = await join_as(events, row.session_id, Role.LECTURER)
    labels = _Labels(["struggling"] * 5 + ["mastered"])
    room.comprehension_source = labels
    question = await deliver_next(room, row)
    assert (
        await room.submit(row.session_id, student, Role.STUDENT, answer_to(question.question_id))
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
