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
from datetime import datetime
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
from app.services.tutor_guardrails import EarlierTurn, OpenQuestion, TutorPrompt, guarded_chat

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


def discussion_chunks(
    notes: tuple[DiscussionSource, ...], question: str, limit: int
) -> list[RetrievedChunk]:
    """Retrieve matching notes or chronological evidence for a session recap."""
    if limit <= 0 or not notes:
        return []

    recap = bool(
        re.search(
            r"\b(miss(?:ed)?|catch.?up|summari[sz]e|recap|"
            r"discuss(?:ed)?|covered|happened|say|said|repeat)\b",
            question,
            re.I,
        )
        or any(
            phrase in question
            for phrase in (
                "\u0645\u0627\u0630\u0627 \u062d\u062f\u062b",
                "\u0645\u0627\u0630\u0627 \u0641\u0627\u062a\u0646\u064a",
                "\u0645\u0644\u062e\u0635",
                "\u0644\u062e\u0635",
                "\u062a\u0644\u062e\u064a\u0635",
                "\u0645\u0627\u0630\u0627 \u062a\u0646\u0627\u0648\u0644\u0646\u0627",
                "\u0634\u0648 \u0635\u0627\u0631",
                "\u0634\u0648 \u0641\u0627\u062a\u0646\u064a",
            )
        )
    )

    ordered = sorted(
        notes,
        key=lambda note: (note.occurred_at, str(note.note_id)),
    )

    if recap:
        recent = bool(
            re.search(r"\b(just|latest|recent|now)\b", question, re.I)
            or "\u0627\u0644\u0622\u0646" in question
            or "\u0645\u0624\u062e\u0631\u0627" in question
        )

        if recent:
            chosen = ordered[-limit:]
        elif len(ordered) <= limit:
            chosen = ordered
        elif limit == 1:
            chosen = [ordered[-1]]
        else:
            chosen = [
                ordered[round(index * (len(ordered) - 1) / (limit - 1))] for index in range(limit)
            ]
    else:
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
            "time",
            "notes",
        }

        terms = set(re.findall(r"[^\W_]{4,}", question.lower())) - stop

        terms.update(re.findall(r"[\u0621-\u064A]{2,}", question))

        def overlap(note: DiscussionSource) -> int:
            words = set(re.findall(r"[^\W_]{4,}", note.text.lower()))
            words.update(re.findall(r"[\u0621-\u064A]{2,}", note.text))
            return len(terms & words)

        chosen = sorted(
            (note for note in ordered if overlap(note) > 0),
            key=lambda note: (
                -overlap(note),
                -note.occurred_at.timestamp(),
            ),
        )[:limit]

    return [
        RetrievedChunk(
            note.note_id,
            index,
            f"{note.origin}, {note.occurred_at.isoformat()}: {note.text}",
            None,
            0.0,
        )
        for index, note in enumerate(chosen)
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
            return discussion_chunks(
                self._context.discussion, question, self._settings.chat_retrieved_chunks
            )
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
                "For broad session catch-up requests, summarize the cited topics in "
                "chronological order with their source timestamps. Respond in the "
                "student's question language when possible. Do not invent missing "
                "topics or translate source quotations inaccurately. "
                "Explain or recap only what "
                "these notes record, with citations. They may be incomplete. Never claim to have "
                "heard the meeting or to cover unrecorded discussion. "
                "Keep the assessment restrictions."
            )
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
            note = next(n for n in self._context.discussion if n.note_id == chunk.chunk_id)
            return {
                "id": str(note.note_id),
                "source_note_id": str(note.note_id),
                "number": number,
                "material_title": (
                    "Automatic live transcript (unreviewed)"
                    if note.origin == "live_transcript"
                    else "Discussion note"
                )
                + f" — {note.occurred_at.isoformat()}",
                "source_page": None,
                "source_slide": None,
                "source_section": None,
                "excerpt": note.text[:CITATION_EXCERPT_CHARS],
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
