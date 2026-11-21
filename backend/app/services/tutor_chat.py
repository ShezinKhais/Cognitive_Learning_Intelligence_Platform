"""One exchange with the tutor, from a student's question to the events they read.

Owner: General CS, Phase 5.

Cyber 1's guarded_chat is the whole path a question takes: it screens the
question, the excerpts, the prompt and the reply, and nothing reaches the
student that has not passed. Revision requests use saved checkpoint results
and a fixed response. For model replies, this module gives the guard:

- The excerpts. The question is embedded and matched against the lecture
  material this session draws on, which is the material its lecturer uploaded
  for its course. Another lecturer's material is never searched.
- The reply. It is streamed from the model through the AI gateway at live
  priority, so it takes its turn with every other model call and a slow model
  cannot hold up the class. When the guard stops reading, or the student
  closes the panel, the gateway stops the model.
- The citations. Each is described from the excerpt it points at and the
  material that excerpt came from.

It also holds each student to one exchange at a time and a few a minute. The
gateway serves whoever is waiting in priority order, and every student in a
class has the same priority, so nothing else stops one of them filling the
queue.

The question is never logged. What is logged is who asked, in which session,
and how the exchange ended.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.errors import ConflictError, RateLimitedError
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.session import Session
from app.repositories.session_repository import SessionRepository
from app.schemas.content import MaterialStatus
from app.services import student_review
from app.services.ai_gateway import AiGateway, AiRequest, Priority, get_ai_gateway
from app.services.discussion import notes_for
from app.services.retrieval import RetrievedChunk
from app.services.source_labels import source_label
from app.services.student_review import RevisionItem
from app.services.tutor_guardrails import (
    MAX_CHUNK_CHARS,
    EarlierTurn,
    OpenQuestion,
    TutorPrompt,
    guarded_chat,
    names_no_topic,
)

log = logging.getLogger("clip.tutor")

# How many of a session's excerpts an overview question picks its spread from.
OVERVIEW_SCAN_LIMIT = 20000

NDJSON = "application/x-ndjson"
RATE_WINDOW_SECONDS = 60.0
# How much of an excerpt a citation shows. Enough to recognise the passage.
CITATION_EXCERPT_CHARS = 240
# Lecture slides are cited by slide, Word and text files by section, and
# everything else by page.
SLIDE_SUFFIXES = (".pptx", ".ppt")


# -- how often a student may ask ------------------------------------------------------


class ChatLimiter:
    """One exchange at a time for each student, and a few a minute.

    Kept in memory, like the hub and the classroom: one process serves a
    class. `longest_exchange` is how long an exchange may be counted as
    running. The exchange normally says when it has ended, but a response
    the client abandons before it starts never runs the code that would, and
    without a limit that student could not ask again until a restart.
    """

    def __init__(
        self,
        per_minute: int,
        longest_exchange: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_minute = per_minute
        self._longest_exchange = longest_exchange
        self._clock = clock
        self._asked: dict[UUID, deque[float]] = {}
        self._running: dict[UUID, float] = {}

    def admit(self, user_id: UUID) -> None:
        """Count a question, or refuse it. An admitted question must be
        followed by finish(), however the exchange ends."""
        now = self._clock()
        started = self._running.get(user_id)
        if started is not None and now - started < self._longest_exchange:
            raise ConflictError("The tutor is still answering your last question.", {})

        asked = self._asked.setdefault(user_id, deque())
        while asked and now - asked[0] >= RATE_WINDOW_SECONDS:
            asked.popleft()
        if len(asked) >= self._per_minute:
            retry_after = max(1, round(RATE_WINDOW_SECONDS - (now - asked[0])))
            raise RateLimitedError(
                "You are asking the tutor too quickly. Try again in a moment.",
                {"retry_after_seconds": retry_after},
            )
        asked.append(now)
        self._running[user_id] = now

    def finish(self, user_id: UUID) -> None:
        self._running.pop(user_id, None)
        asked = self._asked.get(user_id)
        # Nothing recent left to count, so the student is forgotten and the
        # table holds only people who have asked in the last minute.
        if asked is not None and (not asked or self._clock() - asked[-1] >= RATE_WINDOW_SECONDS):
            del self._asked[user_id]


@lru_cache
def get_chat_limiter() -> ChatLimiter:
    settings = get_settings()
    return ChatLimiter(settings.chat_questions_per_minute, longest_exchange(settings))


def longest_exchange(settings: Settings) -> float:
    """The most an exchange can take: a wait for a slot and every attempt to
    embed the question, with the pauses between them, then a wait for a slot
    and the whole streamed reply, whose limit covers its own retries."""
    # The gateway doubles its pause after each failed attempt.
    pauses = settings.ai_retry_pause_seconds * (2 ** (settings.ai_max_attempts - 1) - 1)
    return (
        2 * settings.ai_queue_timeout_seconds
        + settings.ai_request_timeout_seconds * settings.ai_max_attempts
        + pauses
        + settings.ai_stream_timeout_seconds
    )


# -- what an exchange needs from the request ----------------------------------------------


@dataclass(frozen=True)
class MaterialSource:
    title: str
    slides: bool
    sections: bool = False


@dataclass(frozen=True)
class DiscussionSource:
    note_id: UUID
    occurred_at: datetime
    text: str
    origin: str = "lecturer"


async def with_discussion(
    db: AsyncSession, context: ChatContext, since: datetime | None, until: datetime | None
) -> ChatContext:
    notes = await notes_for(db, context.session_id)
    return replace(
        context,
        discussion=tuple(
            DiscussionSource(note.note_id, note.occurred_at, note.text, note.origin)
            for note in notes
            if (since is None or note.occurred_at >= since)
            and (until is None or note.occurred_at <= until)
        ),
    )


# Words that ask for a catch-up rather than name a topic: "What did I miss?",
# "What happened?", "What has the lecturer said so far?". A question that
# names something ("What happened with normalization?") is searched first.
_RECAP_WORDS = re.compile(
    r"\b(miss(?:ed)?|catch.?up|summar(?:y|i[sz]e)|recap|discuss(?:ed)?|cover(?:ed)?|say|said"
    r"|repeat|happen(?:ed|ing|s)?|overview)\b",
    re.I,
)
# Words a catch-up question may use on top of names_no_topic's, without
# naming a topic.
_CATCH_UP_WORDS = frozenset(
    """
    happen happened happening happens miss missed catch say said saying talk talked
    discuss discussed repeat far has came come coming lecturer teacher professor doctor dr sir
    """.split()
)
# "the last 10 minutes", "in the past half hour", "last hour".
_WINDOW = re.compile(
    r"\b(?:in\s+)?(?:the\s+)?(?:last|past|previous|final)\s+"
    r"(?:(\d{1,3}|five|ten|fifteen|twenty|thirty|forty|sixty)\s*(?:min(?:ute)?s?|(hours?|hrs?))"
    r"|(half\s+(?:an\s+)?hour)|(hour))\b",
    re.I,
)
_NUMBER_WORDS = {
    "five": 5,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "sixty": 60,
}
# "What did the lecturer just say?", not "What did I miss? I just joined".
_LATEST_WORDS = re.compile(
    r"\b(just\s+(?:say|said|talk(?:ed)?|explain(?:ed)?|mention(?:ed)?|went\s+over|now)"
    r"|said\s+just\s+now|latest|most\s+recent|recently|right\s+now)\b",
    re.I,
)


def named_window(question: str) -> timedelta | None:
    """The stretch of time a question names, like "the last 10 minutes"."""
    found = _WINDOW.search(question)
    if found is None:
        return None
    amount, hours, half_hour, hour = found.groups()
    if half_hour:
        return timedelta(minutes=30)
    if hour:
        return timedelta(hours=1)
    count = int(amount) if amount.isdigit() else _NUMBER_WORDS[amount.lower()]
    if count == 0:
        return None
    return timedelta(hours=count) if hours else timedelta(minutes=count)


def asks_for_recap(question: str) -> bool:
    """True when the question asks what happened and names no topic."""
    words = re.findall(r"[^\W_]+", _WINDOW.sub(" ", question).casefold())
    if not words:
        # Only a time window, like "last hour?".
        return _WINDOW.search(question) is not None
    rest = [word for word in words if word not in _CATCH_UP_WORDS]
    return not rest or names_no_topic(" ".join(rest))


def _spans(ordered: list[DiscussionSource], count: int) -> list[tuple[DiscussionSource, ...]]:
    """The notes split into consecutive stretches of the session, as even in
    size as they can be."""
    count = min(count, len(ordered))
    bounds = [round(index * len(ordered) / count) for index in range(count + 1)]
    return [tuple(ordered[start:end]) for start, end in zip(bounds, bounds[1:], strict=False)]


def _span_text(span: tuple[DiscussionSource, ...]) -> str:
    """What the model reads for one stretch: every note in it when they fit,
    otherwise every second, third... note, so the whole stretch is still
    represented."""
    first, last = span[0], span[-1]
    if len(span) == 1:
        return f"{first.origin}, {first.occurred_at.isoformat()}: {first.text}"
    text = ""
    for stride in range(1, len(span) + 1):
        shown = span[::stride]
        sampled = "" if stride == 1 else f" ({len(shown)} of {len(span)} notes shown)"
        lines = "\n".join(f"- {note.origin}: {' '.join(note.text.split())}" for note in shown)
        text = (
            f"Notes from {first.occurred_at.isoformat()} to {last.occurred_at.isoformat()}"
            f"{sampled}:\n{lines}"
        )
        if len(text) <= MAX_CHUNK_CHARS:
            break
    return text


def discussion_spans(
    notes: tuple[DiscussionSource, ...], question: str, limit: int
) -> tuple[list[tuple[DiscussionSource, ...]], bool]:
    """The notes to answer from, grouped, and whether this is a catch-up.

    A question about a topic gets the notes that mention it, one to a group.
    A catch-up ("What did I miss?", "What happened?") gets the whole window
    split into up to `limit` consecutive stretches, in time order, so the
    answer can list the session's topics in order. A question naming the
    last few minutes keeps only the notes that long before the latest one.
    Anything else, with no note mentioning it, gets nothing.
    """
    window = named_window(question)
    if window is not None and notes:
        latest = max(note.occurred_at for note in notes)
        notes = tuple(note for note in notes if note.occurred_at >= latest - window)
    if not notes or limit < 1:
        return [], False
    if not asks_for_recap(question):
        matching = _matching_notes(notes, question)
        if matching or not _RECAP_WORDS.search(question):
            return [(note,) for note in matching[:limit]], False
    if _LATEST_WORDS.search(question):
        newest = sorted(notes, key=lambda note: note.occurred_at, reverse=True)
        return [(note,) for note in newest[:limit]], False
    ordered = sorted(notes, key=lambda note: (note.occurred_at, str(note.note_id)))
    return _spans(ordered, limit), True


# Added to the discussion instructions when a student asks for a catch-up.
# Clock times are left to the citations, which the panel shows in the
# student's own time zone; the excerpts carry UTC.
RECAP_NOTE = (
    " The student is catching up. Each excerpt covers one stretch of the session, earliest "
    "first. Reply with a short numbered list of the main topics in the order they came up, "
    "one line each, each ending with the citation of the excerpt it comes from. Skip "
    "greetings and housekeeping unless nothing else was recorded. Do not write clock times: "
    "the citations link each topic to its time. List only topics the excerpts record."
)


def span_title(span: tuple[DiscussionSource, ...]) -> str:
    """A citation's title, saying when automatic speech in it is unreviewed."""
    automatic = sum(note.origin == "live_transcript" for note in span)
    if automatic == len(span):
        label = "Automatic live transcript (unreviewed)"
    elif automatic:
        label = "Discussion notes and automatic live transcript (unreviewed)"
    else:
        label = "Discussion note" if len(span) == 1 else "Discussion notes"
    first, last = span[0].occurred_at.isoformat(), span[-1].occurred_at.isoformat()
    return f"{label} — {first}" + (f" to {last}" if len(span) > 1 else "")


def span_chunk(index: int, span: tuple[DiscussionSource, ...]) -> RetrievedChunk:
    """A group of notes as the excerpt the guard screens, cited by its first note."""
    return RetrievedChunk(span[0].note_id, index, _span_text(span), None, 0.0)


def discussion_chunks(
    notes: tuple[DiscussionSource, ...], question: str, limit: int
) -> list[RetrievedChunk]:
    spans, _ = discussion_spans(notes, question, limit)
    return [span_chunk(index, span) for index, span in enumerate(spans)]


def _matching_notes(notes: tuple[DiscussionSource, ...], question: str) -> list[DiscussionSource]:
    """The notes sharing a word with the question, most shared words first,
    then newest first."""
    stop = {
        "what",
        "when",
        "where",
        "which",
        "this",
        "that",
        "with",
        "from",
        "about",
        "please",
        "explain",
        "could",
        "would",
        "have",
        "were",
        "does",
        "tell",
        "more",
        "session",
        "class",
        "miss",
        "missed",
        "summarize",
        "summarise",
        "recap",
        "discussed",
        "covered",
        "recorded",
        "notes",
        "range",
        "time",
        "main",
        "ideas",
        "said",
        "saying",
        "just",
        "latest",
        "recent",
        "lecturer",
        "teacher",
        "repeat",
        "discuss",
    }
    terms = set(re.findall(r"[^\W_]{4,}", question.lower())) - stop
    scored = [
        (len(terms & set(re.findall(r"[^\W_]{4,}", note.text.lower()))), note) for note in notes
    ]
    return [
        note
        for score, note in sorted(
            scored, key=lambda pair: (pair[0], pair[1].occurred_at), reverse=True
        )
        if score
    ]


@dataclass(frozen=True)
class ChatContext:
    """Everything an exchange needs that only the request's database session
    and signed-in user can supply, gathered before the reply starts. The
    reply outlives the request's session, so it must not reach back for it."""

    session_id: UUID
    user_id: UUID
    open_question: OpenQuestion | None
    materials: dict[UUID, MaterialSource]
    discussion: tuple[DiscussionSource, ...] | None = None


async def prepare(
    db: AsyncSession, live: Session, user_id: UUID, open_question_id: UUID | None
) -> ChatContext:
    """The material this session may be answered from, and the question on
    the student's screen, which the tutor must not help with."""
    materials = {
        material.id: MaterialSource(
            title=material.filename,
            slides=material.filename.lower().endswith(SLIDE_SUFFIXES),
            sections=source_label(material.filename) == "Section",
        )
        for material in await SessionRepository(db).materials_for(live)
        if material.status == MaterialStatus.COMPLETED.value
    }
    open_question = None
    if open_question_id is not None:
        row = await db.get(Question, open_question_id)
        if row is not None:
            # The correct option comes from the stored question. The copy sent
            # to students does not carry it, and the guard needs it to see
            # that a reply has not given the answer away.
            open_question = OpenQuestion(
                prompt=row.question_text,
                options=tuple(row.options or ()),
                correct_option=row.correct_option,
            )
    return ChatContext(
        session_id=live.session_id,
        user_id=user_id,
        open_question=open_question,
        materials=materials,
    )


_REVISION_QUESTIONS = frozenset(
    {
        "what should i revise",
        "what should i revise in this subject",
        "what should i review",
        "what should i study for this course",
    }
)


_SUBJECT_QUESTION = "Which subject would you like to revise?"
_SUBJECT_PREFIX = "Revise "


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip("?.!")


@dataclass(frozen=True)
class RevisionReply:
    text: str
    subjects: tuple[str, ...] = ()
    items: Sequence[RevisionItem] = ()


async def prepare_revision(
    db: AsyncSession, user_id: UUID, question: str, earlier: Sequence[EarlierTurn]
) -> RevisionReply | None:
    ask_for_subject = _normalized(question) in _REVISION_QUESTIONS
    choosing = bool(earlier and earlier[-1].answer.startswith(_SUBJECT_QUESTION))
    explicit_choice = (
        question.casefold().startswith(_SUBJECT_PREFIX.casefold()) and " — " in question
    )
    if not (ask_for_subject or choosing or explicit_choice):
        return None
    subjects = await student_review.revision_subjects(db, user_id)
    if not subjects:
        return (
            RevisionReply("There are no subjects available for revision yet.")
            if ask_for_subject or explicit_choice
            else None
        )
    if not ask_for_subject:
        choice = question[len(_SUBJECT_PREFIX) :] if explicit_choice else question
        selected = [
            subject
            for subject in subjects
            if _normalized(choice)
            in {
                _normalized(subject.code),
                _normalized(subject.name),
                _normalized(f"{subject.code} — {subject.name}"),
            }
        ]
        if len(selected) == 1:
            subject = selected[0]
            items = await student_review.revision_items(db, user_id, subject)
            return RevisionReply(
                f"Revision plan for {subject.code} — {subject.name}."
                if items
                else f"I don’t have any marked answers to flag in {subject.code} — {subject.name} "
                "from completed lessons. You can still ask me about a topic in the current lesson.",
                items=items,
            )
        # The subject picker is one turn in the conversation. A student can
        # change their mind and ask an ordinary tutoring question next.
        if not selected and not explicit_choice:
            return None
    text = _SUBJECT_QUESTION
    if not ask_for_subject:
        text += " Choose a subject below or enter its course code."
    return RevisionReply(
        text, tuple(f"{_SUBJECT_PREFIX}{subject.code} — {subject.name}" for subject in subjects)
    )


async def revision_events(request_id: str, reply: RevisionReply) -> AsyncIterator[dict[str, Any]]:
    """Use recorded facts and source excerpts without sending answers to the model."""
    yield {"type": "accepted", "request_id": request_id}
    yield {"type": "delta", "request_id": request_id, "text": reply.text}
    for subject in reply.subjects:
        yield {"type": "follow_up", "request_id": request_id, "prompt": subject}
    last_lesson = None
    for number, item in enumerate(reply.items, start=1):
        question = " ".join(item.question.split())[:240]
        topic = " ".join((item.topic or "").split())[:100]
        heading = f"Revisit {topic}" if topic else "Revisit this concept"
        source = item.source
        next_step = (
            f"Open the lesson excerpt [{number}], then explain the idea in your own words."
            if source
            else "A lesson excerpt isn’t available for this question. "
            "Use the question to find the topic in your notes or ask your lecturer."
        )
        separator = "\n\n"
        if item.session_id != last_lesson:
            lesson = " ".join(item.lesson.split())[:160]
            separator += f"{lesson} ({item.lesson_date:%Y-%m-%d})\n"
            last_lesson = item.session_id
        yield {
            "type": "delta",
            "request_id": request_id,
            "text": f"{separator}{heading}\nCheckpoint: {question}\n{item.reason} {next_step}",
        }
        if source:
            yield {
                "type": "citation",
                "request_id": request_id,
                "citation": {
                    "id": f"{source.chunk_id}-{number}",
                    "number": number,
                    "material_title": source.material_title,
                    "source_session_id": str(item.session_id),
                    "source_page": source.source_page if source.source_label == "Page" else None,
                    "source_slide": source.source_page if source.source_label == "Slide" else None,
                    "source_section": source.source_page
                    if source.source_label == "Section"
                    else None,
                    "excerpt": " ".join(source.text.split())[:CITATION_EXCERPT_CHARS] or None,
                },
            }
    yield {"type": "completed", "request_id": request_id}


# -- the exchange ---------------------------------------------------------------------


class TutorExchange:
    """Runs one question through the guard and yields what the student reads."""

    def __init__(
        self,
        context: ChatContext,
        *,
        gateway: AiGateway | None = None,
        limiter: ChatLimiter | None = None,
        sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory,
        settings: Settings | None = None,
    ) -> None:
        self._context = context
        self._gateway = gateway or get_ai_gateway()
        self._limiter = limiter or get_chat_limiter()
        self._sessions = sessions
        self._settings = settings or get_settings()
        # Which material each retrieved excerpt came from, for its citation.
        self._found_in: dict[UUID, UUID] = {}
        # The notes each discussion excerpt groups, by the note it is cited
        # by, and whether the question asked for a catch-up.
        self._spans: dict[UUID, tuple[DiscussionSource, ...]] = {}
        self._recap = False

    async def lines(
        self,
        request_id: str,
        question: str,
        earlier: Sequence[EarlierTurn] = (),
        *,
        revision: RevisionReply | None = None,
    ) -> AsyncIterator[bytes]:
        """The reply as NDJSON: one event to a line, as the panel reads it.

        Ends with the exchange counted as finished, whether it completed, was
        refused, failed, or the student stopped reading.
        """
        outcome = "abandoned"
        # No deadline of its own: the gateway already bounds the two model
        # calls, queue included, and nothing else here waits on anything slow.
        events = guarded_chat(
            request_id=request_id,
            question=question,
            open_question=self._context.open_question,
            retrieve=self._retrieve,
            generate=self._generate,
            describe=self._describe,
            earlier=earlier,
            overview=self._overview if self._context.discussion is None else None,
            converse=self._context.discussion is None,
        )
        if revision is not None:
            events = revision_events(request_id, revision)
        try:
            # Closed on the way out, so a reader that stops early still ends
            # the guard, which ends the model's stream.
            async with contextlib.aclosing(events):
                async for event in events:
                    outcome = str(event.get("type"))
                    yield _line(event)
        finally:
            self._limiter.finish(self._context.user_id)
            log.info(
                "tutor exchange session=%s user=%s request=%s outcome=%s",
                self._context.session_id,
                self._context.user_id,
                request_id,
                outcome,
            )

    async def _retrieve(self, question: str) -> Sequence[RetrievedChunk]:
        if self._context.discussion is not None:
            spans, self._recap = discussion_spans(
                self._context.discussion, question, self._settings.chat_retrieved_chunks
            )
            self._spans = {span[0].note_id: span for span in spans}
            return [span_chunk(index, span) for index, span in enumerate(spans)]
        if not self._context.materials:
            return []
        vectors = await self._gateway.embed(
            [question], purpose="tutor_retrieval", priority=Priority.LIVE
        )
        distance = RagChunk.embedding_vector.cosine_distance(vectors[0])
        statement = (
            select(RagChunk, distance.label("distance"))
            .where(
                RagChunk.source_material_id.in_(self._context.materials),
                RagChunk.embedding_vector.isnot(None),
                # Vectors from two models cannot be compared, so excerpts
                # embedded by another model are left out, not ranked.
                RagChunk.embedding_model == self._settings.embedding_model,
            )
            .order_by(distance)
            .limit(self._settings.chat_retrieved_chunks)
        )
        # Its own session, held only for the search. The request's has gone
        # by now, and none is held while the model writes.
        async with self._sessions()() as db:
            rows = (await db.execute(statement)).all()
        found = []
        for row in rows:
            chunk = row.RagChunk
            self._found_in[chunk.chunk_id] = chunk.source_material_id
            found.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    source_page=chunk.source_page,
                    distance=row.distance,
                )
            )
        return found

    async def _overview(self, question: str) -> Sequence[RetrievedChunk]:
        """Excerpts spread evenly across the session's material, in order, for
        a question about the class as a whole ("ask me a question that checks
        my understanding"), which names nothing a search could match."""
        if not self._context.materials:
            return []
        # The same excerpts a search could reach: embedded, by this model.
        reachable = (
            RagChunk.source_material_id.in_(self._context.materials),
            RagChunk.embedding_vector.isnot(None),
            RagChunk.embedding_model == self._settings.embedding_model,
        )
        # Only the ids are scanned, so the spread is chosen without loading
        # every excerpt's text and vector to keep a handful of them.
        listing = (
            select(RagChunk.chunk_id)
            .where(*reachable)
            .order_by(RagChunk.source_material_id, RagChunk.chunk_index)
            .limit(OVERVIEW_SCAN_LIMIT)
        )
        async with self._sessions()() as db:
            ids = list((await db.execute(listing)).scalars().all())
            want = self._settings.chat_retrieved_chunks
            if len(ids) > want:
                last = len(ids) - 1
                ids = [ids[round(i * last / max(want - 1, 1))] for i in range(want)]
            if not ids:
                return []
            picked = (
                select(RagChunk)
                .where(RagChunk.chunk_id.in_(ids))
                .order_by(RagChunk.source_material_id, RagChunk.chunk_index)
            )
            chunks = list((await db.execute(picked)).scalars().all())
        found = []
        for chunk in chunks:
            self._found_in[chunk.chunk_id] = chunk.source_material_id
            found.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    source_page=chunk.source_page,
                    distance=0.0,
                )
            )
        return found

    async def _generate(self, prompt: TutorPrompt) -> AsyncIterator[str]:
        system = prompt.system
        if self._context.discussion is not None:
            system += (
                " The excerpts include reviewed minutes and unreviewed automatic "
                "live speech transcripts. "
                "Automatic speech can contain recognition errors; acknowledge uncertainty. "
                "Explain or recap only what "
                "these notes record, with citations. They may be incomplete. Never claim to have "
                "heard the meeting or to cover unrecorded discussion. "
                "Keep the assessment restrictions."
            )
            if self._recap:
                system += RECAP_NOTE
        request = AiRequest(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt.user},
            ],
            purpose="tutor",
            priority=Priority.LIVE,
        )
        # Leaving this block, as the guard does when it blocks a reply and
        # the server does when the student disconnects, stops the model.
        async with self._gateway.stream(request) as reply:
            async for text in reply:
                yield text

    def _describe(self, chunk: RetrievedChunk, number: int) -> dict[str, Any]:
        """A citation as the panel's parser expects it."""
        if self._context.discussion is not None:
            span = self._spans.get(chunk.chunk_id) or (
                next(n for n in self._context.discussion if n.note_id == chunk.chunk_id),
            )
            note = span[0]
            return {
                "id": str(note.note_id),
                # Links to the first note of the stretch: where the topic starts.
                "source_note_id": str(note.note_id),
                "number": number,
                "material_title": span_title(span),
                "source_page": None,
                "source_slide": None,
                "source_section": None,
                "excerpt": (
                    note.text
                    if len(span) == 1
                    else " ".join(" ".join(n.text.split()) for n in span)
                )[:CITATION_EXCERPT_CHARS],
            }
        source = self._context.materials[self._found_in[chunk.chunk_id]]
        excerpt = " ".join(chunk.chunk_text.split())[:CITATION_EXCERPT_CHARS]
        return {
            "id": str(chunk.chunk_id),
            # The [n] the answer cites it by, so the panel can link the two.
            "number": number,
            "material_title": source.title,
            "source_page": None if source.slides or source.sections else chunk.source_page,
            "source_slide": chunk.source_page if source.slides else None,
            "source_section": chunk.source_page if source.sections else None,
            "excerpt": excerpt or None,
        }


def _line(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode()
