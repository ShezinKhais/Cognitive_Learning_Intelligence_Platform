"""Tests for the real transcript-aware question selection service."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import lecture_checkpoint_selection as selection


class FakeDb:
    def __init__(self, notes):
        self.notes = notes
        self.queries = []

    async def scalars(self, query):
        self.queries.append(query)
        return SimpleNamespace(all=lambda: self.notes)


class FakeQuestionRepository:
    candidates = []
    calls = []

    def __init__(self, db):
        self.db = db

    async def list_deliverable(self, session, *, limit, offset):
        self.calls.append((session.session_id, limit, offset))
        return self.candidates[offset : offset + limit], len(self.candidates)


@pytest.fixture
def fake_repository(monkeypatch):
    FakeQuestionRepository.candidates = []
    FakeQuestionRepository.calls = []
    monkeypatch.setattr(
        selection, "SessionRepository", FakeQuestionRepository
    )
    return FakeQuestionRepository


def note(at, text, origin="live_transcript"):
    return SimpleNamespace(
        occurred_at=at,
        text=text,
        origin=origin,
    )


def question(text, topic):
    return SimpleNamespace(
        question_id=uuid4(),
        question_text=text,
        topic=topic,
    )


async def test_selects_taught_question_not_earlier_unrelated_question(
    fake_repository,
):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    session = SimpleNamespace(session_id=uuid4())

    db = FakeDb([
        note(now - timedelta(minutes=8), "We discussed enzymes and inhibition.")
    ])

    animals = question("What are mammals?", "mammals")
    enzymes = question("What is enzyme inhibition?", "enzyme")

    fake_repository.candidates = [animals, enzymes]

    selected = await selection.choose_recent_question(db, session, now)

    assert selected == enzymes.question_id
    assert fake_repository.calls == [(session.session_id, 100, 0)]

    # Verify database query scopes the evidence to this session,
    # transcript origin and the correct 20-minute window.
    params = list(db.queries[0].compile().params.values())
    assert session.session_id in params
    assert "live_transcript" in params
    assert now - timedelta(minutes=20) in params
    assert now in params


async def test_no_recent_transcript_skips_all_questions(fake_repository):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    session = SimpleNamespace(session_id=uuid4())

    db = FakeDb([
        note(now - timedelta(minutes=25), "Enzymes and inhibition."),
        note(now - timedelta(minutes=3), "Enzymes and inhibition.", "lecturer"),
    ])

    fake_repository.candidates = [
        question("What is enzyme inhibition?", "enzyme")
    ]

    selected = await selection.choose_recent_question(db, session, now)

    assert selected is None
    assert fake_repository.calls == []


async def test_no_supported_question_abstains(fake_repository):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    session = SimpleNamespace(session_id=uuid4())

    db = FakeDb([
        note(now - timedelta(minutes=5), "Today we studied enzymes.")
    ])

    fake_repository.candidates = [
        question("What are mammals?", "mammals"),
        question("What is enzyme inhibition?", "enzyme"),
    ]

    selected = await selection.choose_recent_question(db, session, now)

    assert selected is None
    assert len(fake_repository.calls) == 1


async def test_can_choose_question_on_later_candidate_page(fake_repository):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    session = SimpleNamespace(session_id=uuid4())
    db = FakeDb([
        note(now - timedelta(minutes=2), "Enzyme inhibition was discussed.")
    ])

    unrelated = [question("What are mammals?", "mammals") for _ in range(100)]
    matched = question("What is enzyme inhibition?", "enzyme")
    fake_repository.candidates = unrelated + [matched]

    selected = await selection.choose_recent_question(db, session, now)

    assert selected == matched.question_id
    assert [call[2] for call in fake_repository.calls] == [0, 100]
