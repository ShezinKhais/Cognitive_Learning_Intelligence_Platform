"""One exchange with the tutor, from a student's question to the events they read.

Owner: General CS, Phase 5.

Cyber 1's guarded_chat is the whole path a question takes: it screens the
question, the excerpts, the prompt and the reply, and nothing reaches the
student that has not passed. It asks its caller for three things, and this
module is that caller:

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
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
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
from app.services.ai_gateway import AiGateway, AiRequest, Priority, get_ai_gateway
from app.services.retrieval import RetrievedChunk
from app.services.tutor_guardrails import OpenQuestion, TutorPrompt, guarded_chat

log = logging.getLogger("clip.tutor")

NDJSON = "application/x-ndjson"
RATE_WINDOW_SECONDS = 60.0
# How much of an excerpt a citation shows. Enough to recognise the passage.
CITATION_EXCERPT_CHARS = 240
# Lecture slides are cited by slide, everything else by page.
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
    """The most an exchange can take: a wait for a slot and an attempt to
    embed the question, then a wait for a slot and the whole streamed reply."""
    return (
        2 * settings.ai_queue_timeout_seconds
        + settings.ai_request_timeout_seconds * settings.ai_max_attempts
        + settings.ai_stream_timeout_seconds
    )


# -- what an exchange needs from the request ----------------------------------------------


@dataclass(frozen=True)
class MaterialSource:
    title: str
    slides: bool


@dataclass(frozen=True)
class ChatContext:
    """Everything an exchange needs that only the request's database session
    and signed-in user can supply, gathered before the reply starts. The
    reply outlives the request's session, so it must not reach back for it."""

    session_id: UUID
    user_id: UUID
    open_question: OpenQuestion | None
    materials: dict[UUID, MaterialSource]


async def prepare(
    db: AsyncSession, live: Session, user_id: UUID, open_question_id: UUID | None
) -> ChatContext:
    """The material this session may be answered from, and the question on
    the student's screen, which the tutor must not help with."""
    materials = {
        material.id: MaterialSource(
            title=material.filename,
            slides=material.filename.lower().endswith(SLIDE_SUFFIXES),
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

    async def lines(self, request_id: str, question: str) -> AsyncIterator[bytes]:
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
        )
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

    async def _generate(self, prompt: TutorPrompt) -> AsyncIterator[str]:
        request = AiRequest(
            messages=[
                {"role": "system", "content": prompt.system},
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
        source = self._context.materials[self._found_in[chunk.chunk_id]]
        excerpt = " ".join(chunk.chunk_text.split())[:CITATION_EXCERPT_CHARS]
        return {
            "id": str(chunk.chunk_id),
            "material_title": source.title,
            "source_page": None if source.slides else chunk.source_page,
            "source_slide": chunk.source_page if source.slides else None,
            "excerpt": excerpt or None,
        }


def _line(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode()
