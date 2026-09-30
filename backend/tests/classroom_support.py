"""Fakes shared by the classroom tests: sockets that record what they are
sent, and a session repository that is a queue of staged questions.

The fake_session_repository fixture swaps the fake in. conftest.py registers
this module as a plugin, and each classroom test module asks for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.realtime import classroom as classroom_module
from app.realtime.classroom import Classroom
from app.realtime.hub import Connection, SessionHub
from app.schemas.events import (
    AnswerSubmitPayload,
    ServerEventType,
)
from app.schemas.identity import Role
from app.schemas.session import SessionStatus


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        return None

    def of(self, event_type: ServerEventType) -> list[dict]:
        return [m for m in self.sent if m["type"] == event_type.value]


@dataclass
class StagedQuestion:
    question_text: str = "Which planet is largest?"
    options: list[str] | None = field(default_factory=lambda: ["Mars", "Jupiter", "Venus"])
    correct_option: int | None = 1
    source_slide: int | None = 4
    question_id: UUID = field(default_factory=uuid4)
    question_type: str | None = None

    def __post_init__(self) -> None:
        if self.question_type is None:
            self.question_type = "mcq" if self.options else "free_text"


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> FakeDb:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeRepository:
    """Stands in for SessionRepository: a queue of staged questions."""

    staged: list[StagedQuestion] = []
    # What each claim was told about the delivery it records.
    deliveries: list[dict] = []
    rows: dict[UUID, SimpleNamespace] = {}

    def __init__(self, db: object) -> None:
        pass

    async def claim_for_delivery(self, row, question_id=None, **delivery):  # noqa: ANN001, ANN003, ANN201
        FakeRepository.deliveries.append(delivery)
        for question in FakeRepository.staged:
            if question_id is None or question.question_id == question_id:
                FakeRepository.staged.remove(question)
                return question
        return None

    async def count_delivered(self, session_id: UUID) -> int:
        return 0

    async def get(self, session_id: UUID, *, for_update: bool = False):  # noqa: ANN201
        return FakeRepository.rows.get(session_id)


def make_room(
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
        sessions=lambda: FakeDb,
        settings=lambda: settings,
        rng=rng,  # type: ignore[arg-type]
    )
    return room, events


def make_row(session_id: UUID | None = None) -> SimpleNamespace:
    row = SimpleNamespace(
        session_id=session_id or uuid4(), status=SessionStatus.ACTIVE.value, paused_at=None
    )
    FakeRepository.rows[row.session_id] = row
    return row


async def join_as(events: SessionHub, session_id: UUID, role: Role, user: UUID | None = None):
    socket = FakeSocket()
    user = user or uuid4()
    await events.join(Connection(socket, user, session_id, role))  # type: ignore[arg-type]
    return socket, user


def answer_to(question_id: UUID, option: int | None = 1, text: str | None = None):
    return AnswerSubmitPayload(
        question_id=question_id, selected_option=option, free_text=text, client_elapsed_ms=900
    )


async def deliver_next(room: Classroom, row: SimpleNamespace) -> StagedQuestion:
    question = StagedQuestion()
    FakeRepository.staged.append(question)
    assert await room.deliver(FakeDb(), row) is not None  # type: ignore[arg-type]
    return question


@pytest.fixture
def fake_session_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeRepository.staged = []
    FakeRepository.rows = {}
    FakeRepository.deliveries = []
    monkeypatch.setattr(classroom_module, "SessionRepository", FakeRepository)
