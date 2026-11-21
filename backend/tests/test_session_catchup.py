"""Catch-up answers: "What happened?" gets an ordered overview of the session (#318).

A student asking what they missed names no topic, so the notes are not
searched for their words. The window is split into consecutive stretches, in
time order, each cited by where it starts, and the tutor is asked for a short
ordered list of topics. A question about a topic still gets the notes that
mention it, and one about something never discussed still gets nothing.
"""

import contextlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.auth.store import STUDENT_ID
from app.services.tutor_chat import (
    RECAP_NOTE,
    ChatContext,
    ChatLimiter,
    DiscussionSource,
    TutorExchange,
    asks_for_recap,
    discussion_chunks,
    discussion_spans,
    named_window,
    span_title,
)
from app.services.tutor_guardrails import MAX_CHUNK_CHARS

START = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


def lecture(minutes: int, *, every: int = 1, origin: str = "live_transcript"):
    """One note a minute (or every `every` minutes), each naming its minute."""
    return tuple(
        DiscussionSource(
            uuid4(), START + timedelta(minutes=m), f"At minute {m} we covered topic {m}.", origin
        )
        for m in range(0, minutes, every)
    )


SHORT = (
    DiscussionSource(uuid4(), START, "We start with database normalization.", "lecturer"),
    DiscussionSource(
        uuid4(), START + timedelta(minutes=5), "First normal form removes repeating groups."
    ),
    DiscussionSource(
        uuid4(), START + timedelta(minutes=10), "Indexes use B-trees.", "live_transcript"
    ),
    DiscussionSource(
        uuid4(), START + timedelta(minutes=15), "Homework is due Friday.", "live_transcript"
    ),
)


# -- which questions are catch-ups -----------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What did I miss?",
        "What happened?",
        "What happened in the last 10 minutes?",
        "Give me an overview",
        "What was the lecture about?",
        "What topics came up?",
        "What has the lecturer said so far?",
        "Summarise the past half hour",
        "Can you recap the session?",
        "last hour?",
    ],
)
def test_ways_of_asking_what_happened_get_the_whole_window(question) -> None:
    spans, recap = discussion_spans(SHORT, question, 5)
    assert recap, question
    kept = [note for span in spans for note in span]
    assert kept, question
    # In time order, ending at the latest note.
    assert kept == sorted(kept, key=lambda note: note.occurred_at)
    assert kept[-1] is SHORT[-1]


def test_what_happened_used_to_find_nothing() -> None:
    """The bug #318 names: no word of "What happened?" is in the notes, and
    "happened" was not a catch-up word, so the student was told there were
    no sources."""
    assert len(discussion_chunks(SHORT, "What happened?", 5)) == len(SHORT)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Explain normalization", [0]),
        ("What happened with indexes?", [2]),
        ("When is the homework due?", [3]),
    ],
)
def test_a_question_that_names_a_topic_gets_the_notes_that_mention_it(question, expected):
    spans, recap = discussion_spans(SHORT, question, 5)
    assert not recap
    assert [span[0] for span in spans] == [SHORT[i] for i in expected]


@pytest.mark.parametrize(
    "question", ["Explain photosynthesis", "Tell me about photosynthesis", "What is 404?"]
)
def test_a_topic_never_discussed_gets_nothing(question) -> None:
    assert discussion_chunks(SHORT, question, 5) == []
    assert not asks_for_recap(question)


@pytest.mark.parametrize(
    "question",
    ["What did the lecturer just say?", "What was said just now?", "Repeat the latest point"],
)
def test_what_was_just_said_is_the_newest_notes_first(question) -> None:
    spans, recap = discussion_spans(SHORT, question, 2)
    assert not recap
    assert [span[0] for span in spans] == [SHORT[3], SHORT[2]]


def test_someone_who_just_joined_gets_the_whole_catch_up() -> None:
    """ "just" alone does not mean "what was just said"."""
    spans, recap = discussion_spans(SHORT, "What did I miss? I just joined", 5)
    assert recap
    assert spans == [(note,) for note in SHORT]


# -- empty, short and long sessions ----------------------------------------------------------


def test_an_empty_session_has_nothing_to_recap() -> None:
    assert discussion_spans((), "What did I miss?", 5) == ([], False)


def test_a_short_session_is_one_note_to_each_stretch_in_order() -> None:
    spans, recap = discussion_spans(SHORT, "What did I miss?", 5)
    assert recap
    assert spans == [(note,) for note in SHORT]


def test_a_long_session_is_split_into_consecutive_stretches_that_cover_all_of_it() -> None:
    notes = lecture(90)
    spans, recap = discussion_spans(notes, "What did I miss?", 5)
    assert recap and len(spans) == 5
    # Every note is in exactly one stretch, in time order, and the stretches
    # are as even as they can be.
    assert [note for span in spans for note in span] == list(notes)
    assert {len(span) for span in spans} == {18}
    chunks = discussion_chunks(notes, "What did I miss?", 5)
    assert [chunk.chunk_id for chunk in chunks] == [span[0].note_id for span in spans]
    assert "topic 0." in chunks[0].chunk_text and "topic 89." in chunks[-1].chunk_text


def test_a_stretch_too_long_to_show_whole_is_sampled_across_it_and_says_so() -> None:
    notes = tuple(
        DiscussionSource(uuid4(), START + timedelta(seconds=10 * i), f"Segment {i}. " + "x" * 150)
        for i in range(300)
    )
    chunks = discussion_chunks(notes, "What happened?", 5)
    assert len(chunks) == 5
    for chunk in chunks:
        assert len(chunk.chunk_text) <= MAX_CHUNK_CHARS
        assert "notes shown)" in chunk.chunk_text
    # The first stretch still runs from its first segment towards its end.
    assert "Segment 0." in chunks[0].chunk_text and "Segment 5" in chunks[0].chunk_text


# -- time windows ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "window"),
    [
        ("What happened in the last 10 minutes?", timedelta(minutes=10)),
        ("Recap the past 5 mins", timedelta(minutes=5)),
        ("What did I miss in the last ten minutes?", timedelta(minutes=10)),
        ("Summarise the last half an hour", timedelta(minutes=30)),
        ("What happened in the past hour?", timedelta(hours=1)),
        ("Recap the last 2 hours", timedelta(hours=2)),
        ("What did I miss?", None),
        ("Explain the last normal form", None),
    ],
)
def test_a_named_time_window_is_read(question, window) -> None:
    assert named_window(question) == window


def test_the_last_10_minutes_keeps_only_those_minutes_of_the_record() -> None:
    """Measured back from the latest note, which during class is the most
    recent speech and after class is where the record ends."""
    notes = lecture(60)
    spans, recap = discussion_spans(notes, "What happened in the last 10 minutes?", 5)
    assert recap
    kept = [note for span in spans for note in span]
    assert kept == list(notes[49:])  # minutes 49 to 59: ten minutes back from 59


def test_a_topic_question_with_a_window_searches_only_that_window() -> None:
    notes = lecture(60)
    # Every note mentions "minute", but only those in the last ten minutes count.
    spans, recap = discussion_spans(notes, "Explain the minute in the last 10 minutes", 5)
    assert not recap and len(spans) == 5
    assert all(span[0].occurred_at >= START + timedelta(minutes=49) for span in spans)


# -- the exchange: prompt and citations ------------------------------------------------------


class Model:
    """A gateway that records what it was asked and replies with `reply`."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests = []

    @contextlib.asynccontextmanager
    async def stream(self, request):
        self.requests.append(request)

        async def text():
            yield self.reply

        yield text()


async def _ask(notes, question: str, reply: str):
    model = Model(reply)
    limiter = ChatLimiter(30, 60)
    limiter.admit(STUDENT_ID)
    context = ChatContext(
        session_id=uuid4(), user_id=STUDENT_ID, open_question=None, materials={}, discussion=notes
    )
    exchange = TutorExchange(context, gateway=model, limiter=limiter)
    events = [json.loads(line) async for line in exchange.lines("req-1", question)]
    return model, events


async def test_a_catch_up_asks_for_an_ordered_list_and_cites_each_stretch() -> None:
    notes = lecture(90)
    model, events = await _ask(
        notes,
        "What happened?",
        "1. Topics 0 to 17 [1]\n2. Topics 18 to 35 [2]\n3. Topics 36 to 53 [3]\n"
        "4. Topics 54 to 71 [4]\n5. Topics 72 to 89 [5]\nWhich one is new to you?",
    )
    system = model.requests[0].messages[0]["content"]
    assert RECAP_NOTE in system
    citations = [event["citation"] for event in events if event["type"] == "citation"]
    assert len(citations) == 5, events
    first = citations[0]
    assert first["source_note_id"] == str(notes[0].note_id)
    # Automatic speech is marked unreviewed, with the stretch's start and end.
    assert first["material_title"] == (
        f"Automatic live transcript (unreviewed) — {notes[0].occurred_at.isoformat()} "
        f"to {notes[17].occurred_at.isoformat()}"
    )
    assert events[-1]["type"] == "completed", events


def test_a_stretch_mixing_minutes_and_automatic_speech_says_it_is_partly_unreviewed():
    mixed = (
        DiscussionSource(uuid4(), START, "Normalization reduces duplicates.", "lecturer"),
        DiscussionSource(
            uuid4(), START + timedelta(minutes=2), "Repeating groups go.", "live_transcript"
        ),
    )
    assert span_title(mixed) == (
        "Discussion notes and automatic live transcript (unreviewed) — "
        f"{START.isoformat()} to {mixed[1].occurred_at.isoformat()}"
    )
    assert span_title(mixed[:1]) == f"Discussion note — {START.isoformat()}"


async def test_a_topic_question_is_not_answered_as_a_catch_up() -> None:
    model, events = await _ask(
        SHORT, "Explain normalization", "Normalization removes duplicates [1]. Why does it help?"
    )
    assert RECAP_NOTE not in model.requests[0].messages[0]["content"]
    (citation,) = [event["citation"] for event in events if event["type"] == "citation"]
    assert citation["material_title"] == f"Discussion note — {SHORT[0].occurred_at.isoformat()}"


async def test_a_catch_up_on_an_empty_session_says_there_is_nothing_recorded() -> None:
    model, events = await _ask((), "What did I miss?", "unused")
    assert model.requests == []
    assert [event["type"] for event in events][-1] == "empty_retrieval", events
