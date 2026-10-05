"""Runs model calls for the rest of the application.

Owner: General CS, Phase 5.

A model call is the slowest thing this service does. A reply takes seconds
when the model is loaded and the best part of a minute when it is not, and
the model serves a handful of requests at a time however many are sent. Left
to themselves, a class of forty asking the chatbot at once, a free-text
answer waiting to be classified and a lecturer's upload generating questions
all reach for the same model together, and every one of them gets slower.

So every call goes through here, and this module owes its callers five
things:

- A bounded slot. At most `max_concurrency` calls reach the model at once.
  The rest wait in priority order, so a student in a live class is served
  before an upload nobody is watching. The wait is bounded too: a full queue
  refuses at once, and a request that has waited too long gives up, since an
  answer that arrives a minute late is worse than being told to try again.
- A deadline. No call waits on the model for ever, and a stream that goes
  quiet is ended.
- Another try. A call that could not reach the model is retried with a
  growing pause. A stream is only retried until its first word: after that
  the reader has seen text, and a second attempt would repeat it.
- A way out. After several failures in a row the model is left alone for a
  while and callers are refused at once, instead of each waiting out a
  timeout against something that is down. A caller that passes `fallback`
  gets that text back in place of an error.
- Cancellation that reaches the model. Leaving a stream, cancelling it or
  cancelling the task that waits on a call closes the connection and frees
  the slot, including while the request is still queued.

Nothing here runs on the request path of a live session. Every wait is an
await, so the event loop keeps serving sockets while the model thinks, and
the slot limit keeps model work from crowding out everything else.

Embeddings take the same route as replies. They are quick, but the chatbot
embeds every question a student asks before it can search the material, so
in a live class they are as much a part of the load as the replies are.

The model server unloads a model nobody has used for a few minutes, and
loading it again takes longer than a student will wait. So the gateway loads
it at startup and then keeps it loaded, by asking for one word whenever the
model has sat idle for a while.

What a prompt says, what a reply may contain and what is stored about either
belong to the workstreams that call this. Prompts and replies are never
logged here: they carry students' own words.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from functools import lru_cache
from types import SimpleNamespace
from typing import Protocol, TypeVar

import openai
from openai import AsyncOpenAI

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError

log = logging.getLogger("clip.ai")

Message = dict[str, str]
T = TypeVar("T")

# What the warm-up sends. One token of output is enough to make the model
# server load the weights, which is the whole point.
WARMUP_MESSAGES: tuple[Message, ...] = ({"role": "user", "content": "Reply with OK."},)
WARMUP_TEXT = "ok"
# A development machine often has no model server. After this many tries the
# warm-up stops and says so once, instead of warning every minute for ever.
WARMUP_ATTEMPTS = 5
WARMUP_FIRST_PAUSE_SECONDS = 2.0
WARMUP_MAX_PAUSE_SECONDS = 60.0


class Priority(IntEnum):
    """Who is waiting on a call. Lower is served first."""

    # A student or lecturer in a running class.
    LIVE = 0
    # Someone is looking at the screen, outside a class.
    INTERACTIVE = 1
    # Nobody is watching: material processing.
    BACKGROUND = 2


class AiStatus(StrEnum):
    COLD = "cold"
    WARMING = "warming"
    READY = "ready"
    # Refusing calls after repeated failures.
    UNAVAILABLE = "unavailable"


# -- errors -----------------------------------------------------------------------


class AiUnavailableError(ServiceUnavailableError):
    """The model could not be reached, or was not asked. Safe to retry later."""

    code = "AI_UNAVAILABLE"
    log_traceback = False


class AiBusyError(AiUnavailableError):
    """Too many calls are already waiting, or this one waited too long."""

    code = "AI_BUSY"


class AiRejectedError(AiUnavailableError):
    """The model refused the request itself, so sending it again will not help."""

    code = "AI_REJECTED"


class AiInterruptedError(AiUnavailableError):
    """A stream stopped after part of the reply had been delivered."""

    code = "AI_INTERRUPTED"


class ModelUnreachableError(Exception):
    """Raised by a ModelClient when the model server did not answer usefully.

    `retry` is false when asking this model again cannot help, such as a
    model that is not installed. A fallback model is still worth trying.
    """

    def __init__(self, reason: str, *, retry: bool = True) -> None:
        super().__init__(reason)
        self.retry = retry


class ModelRejectedError(Exception):
    """Raised by a ModelClient when the server answered and refused the request."""


# -- the model client --------------------------------------------------------------


class ModelClient(Protocol):
    """One attempt at the model. No queueing, retrying or timing of its own."""

    async def complete(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> str: ...

    def stream(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> AsyncIterator[str]: ...

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]: ...


# Statuses that say "not now" rather than "not this request".
_RETRYABLE_STATUSES = frozenset({408, 409, 425, 429})


def _translated(exc: openai.OpenAIError) -> Exception:
    """An openai error as one of the two a ModelClient may raise."""
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code == 404:
            # The model is not installed on the server. The server itself is fine.
            return ModelUnreachableError("the model is not installed", retry=False)
        if exc.status_code >= 500 or exc.status_code in _RETRYABLE_STATUSES:
            return ModelUnreachableError(f"HTTP {exc.status_code}")
        return ModelRejectedError(f"HTTP {exc.status_code}")
    # No answer at all: refused, reset, timed out, or one that made no sense.
    return ModelUnreachableError(type(exc).__name__)


class OpenAIModelClient:
    """The OpenAI-compatible endpoint Ollama serves."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def complete(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=model, messages=list(messages), **_options(max_tokens)
            )
        except openai.OpenAIError as exc:
            raise _translated(exc) from exc
        return response.choices[0].message.content or ""

    async def stream(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> AsyncIterator[str]:
        try:
            response = await self._client.chat.completions.create(
                model=model, messages=list(messages), stream=True, **_options(max_tokens)
            )
        except openai.OpenAIError as exc:
            raise _translated(exc) from exc
        try:
            async for chunk in response:
                text = chunk.choices[0].delta.content if chunk.choices else None
                if text:
                    yield text
        except openai.OpenAIError as exc:
            raise _translated(exc) from exc
        finally:
            # Also reached when the reader stops early or is cancelled, which
            # is what tells the server to stop generating.
            await response.close()

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(model=model, input=list(texts))
        except openai.OpenAIError as exc:
            raise _translated(exc) from exc
        # By the index each vector carries, not the order they arrived in.
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


def _options(max_tokens: int | None) -> dict[str, int]:
    return {} if max_tokens is None else {"max_tokens": max_tokens}


# -- requests and results -----------------------------------------------------------


@dataclass(frozen=True)
class AiLimits:
    """How long and how hard the gateway tries. Seconds throughout."""

    max_concurrency: int = 2
    queue_limit: int = 32
    queue_timeout: float = 20.0
    # One attempt of complete().
    request_timeout: float = 60.0
    # A stream: its first word, the gap between words, and the whole reply.
    first_token_timeout: float = 30.0
    stream_idle_timeout: float = 15.0
    stream_timeout: float = 120.0
    max_attempts: int = 3
    retry_pause: float = 0.5
    breaker_failures: int = 5
    breaker_cooldown: float = 30.0
    warmup_timeout: float = 120.0
    # How long the model may sit idle before it is asked for a word, so the
    # server does not unload it. 0 never asks.
    keep_warm_interval: float = 240.0

    @classmethod
    def from_settings(cls, settings: Settings) -> AiLimits:
        return cls(
            max_concurrency=settings.ai_max_concurrency,
            queue_limit=settings.ai_queue_limit,
            queue_timeout=settings.ai_queue_timeout_seconds,
            request_timeout=settings.ai_request_timeout_seconds,
            first_token_timeout=settings.ai_first_token_timeout_seconds,
            stream_idle_timeout=settings.ai_stream_idle_timeout_seconds,
            stream_timeout=settings.ai_stream_timeout_seconds,
            max_attempts=settings.ai_max_attempts,
            retry_pause=settings.ai_retry_pause_seconds,
            breaker_failures=settings.ai_breaker_failures,
            breaker_cooldown=settings.ai_breaker_cooldown_seconds,
            warmup_timeout=settings.ai_warmup_timeout_seconds,
            keep_warm_interval=settings.ai_keep_warm_seconds,
        )


@dataclass(frozen=True)
class AiRequest:
    """One call to the model.

    `purpose` names the caller for the log, such as "chat" or
    "classification". `fallback`, when given, is returned in place of an
    error if the model cannot answer. `timeout` and `max_attempts` override
    the gateway's limits for one attempt of this call, and `queue_timeout`
    how long it may wait for a slot: work nobody is watching can afford to
    wait far longer than a student can.
    """

    messages: Sequence[Message]
    purpose: str
    priority: Priority = Priority.INTERACTIVE
    model: str | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    max_attempts: int | None = None
    queue_timeout: float | None = None
    fallback: str | None = None


@dataclass(frozen=True)
class AiResult:
    """`model` is the one that answered, which a caller storing the result
    should record. It is None, and `fallback` true, when the text is the
    request's fallback and no model wrote it."""

    text: str
    model: str | None
    attempts: int
    fallback: bool = False


# -- waiting for a slot --------------------------------------------------------------


class _Slots:
    """A counted limit whose waiters are served by priority, then by arrival.

    Kept as plain counters and one future per waiter, so nothing is bound to
    the event loop that happened to create the gateway.
    """

    def __init__(self, limit: int, queue_limit: int) -> None:
        self._free = limit
        self._queue_limit = queue_limit
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._waiting = 0
        self._order = itertools.count()

    @property
    def waiting(self) -> int:
        return self._waiting

    async def acquire(self, priority: Priority, patience: float) -> None:
        if self._free > 0 and self._waiting == 0:
            self._free -= 1
            return
        if self._waiting >= self._queue_limit:
            raise AiBusyError("The assistant is busy. Try again shortly.", {})
        granted: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (int(priority), next(self._order), granted))
        self._waiting += 1
        try:
            async with asyncio.timeout(patience):
                await granted
        except BaseException as exc:
            if granted.done() and not granted.cancelled():
                # The slot was handed over as this waiter gave up. It is ours,
                # so pass it on rather than lose it.
                self.release()
            else:
                granted.cancel()
                self._waiting -= 1
            if isinstance(exc, TimeoutError):
                raise AiBusyError("The assistant is busy. Try again shortly.", {}) from None
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, granted = heapq.heappop(self._waiters)
            if not granted.done():
                self._waiting -= 1
                granted.set_result(None)
                return
        self._free += 1


@dataclass
class _Warmth:
    """What is known about whether the server still has a model loaded."""

    model: str
    # It has answered at least once since the process started.
    loaded: bool = False
    # When it last answered a call, and when it was last asked to stay loaded.
    used: float = 0.0
    asked: float = 0.0

    def answered(self, now: float) -> None:
        self.loaded = True
        self.used = now

    def due(self, interval: float) -> float:
        """When it next needs a word to stay loaded."""
        return max(self.used, self.asked) + interval


class _Breaker:
    """Stops calls reaching a model that keeps failing.

    Closed, it lets everything through and counts failures in a row. At the
    limit it opens and refuses for the cool-down. After that one call is let
    through as a trial: its success closes the breaker, its failure opens it
    again.
    """

    def __init__(
        self, failures: int, cooldown: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = failures
        self._cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._open_until: float | None = None
        self._trial = False

    @property
    def refusing(self) -> bool:
        """Whether a call arriving now would be refused. Changes nothing."""
        if self._open_until is None:
            return False
        return self._trial or self._clock() < self._open_until

    def allow(self) -> bool:
        if self._open_until is None:
            return True
        if self._trial or self._clock() < self._open_until:
            return False
        self._trial = True
        return True

    def success(self) -> None:
        self._failures = 0
        self._open_until = None
        self._trial = False

    def failure(self) -> None:
        self._failures += 1
        if self._trial or self._failures >= self._limit:
            self._open_until = self._clock() + self._cooldown
        self._trial = False

    def abandon(self) -> None:
        """The call ended without learning anything, as a cancelled one does."""
        self._trial = False


# -- streams -----------------------------------------------------------------------


class AiStream:
    """A reply as it is written. Iterate it for the text, piece by piece.

    The iteration ends when the reply does, or when cancel() is called. It
    raises AiInterruptedError if the model stopped partway, and
    AiUnavailableError if it never started and the request had no fallback.
    `text` is everything delivered so far, and `model` who wrote it.
    """

    def __init__(self) -> None:
        self.text = ""
        self.model: str | None = None
        self.attempts = 0
        self.fallback = False
        self.cancelled = False
        self._items: asyncio.Queue[str | Exception | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._finished = False
        self._ended = False

    def __aiter__(self) -> AiStream:
        return self

    async def __anext__(self) -> str:
        if self._ended:
            raise StopAsyncIteration
        item = await self._items.get()
        if isinstance(item, str):
            return item
        self._ended = True
        if item is None:
            raise StopAsyncIteration
        raise item

    def cancel(self) -> None:
        """Stop the reply. Safe from any task, and after it has finished."""
        if self._task is not None and not self._task.done():
            self.cancelled = True
            self._task.cancel()

    def _deliver(self, text: str) -> None:
        self.text += text
        self._items.put_nowait(text)

    def _finish(self, error: Exception | None = None) -> None:
        """End the reply, once. Called by the task that writes it, and again
        when that task is done: a task cancelled before it ran a step never
        reaches its own finally, and the reader would wait for ever."""
        if not self._finished:
            self._finished = True
            self._items.put_nowait(error)


# -- the gateway ---------------------------------------------------------------------


class AiGateway:
    """Every model call in the process goes through one of these."""

    def __init__(
        self,
        client: ModelClient,
        model: str,
        limits: AiLimits | None = None,
        *,
        fallback_model: str | None = None,
        embedding_model: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._model = model
        self._fallback_model = fallback_model or None
        self._embedding_model = embedding_model or None
        self._limits = limits or AiLimits()
        self._slots = _Slots(self._limits.max_concurrency, self._limits.queue_limit)
        self._breaker = _Breaker(
            self._limits.breaker_failures, self._limits.breaker_cooldown, clock
        )
        self._clock = clock
        self._chat = _Warmth(model, used=clock())
        self._embedder = (
            _Warmth(self._embedding_model, used=clock()) if self._embedding_model else None
        )
        self._warming: asyncio.Task[None] | None = None
        self._streams: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def model(self) -> str:
        return self._model

    @property
    def status(self) -> AiStatus:
        if self._breaker.refusing:
            return AiStatus.UNAVAILABLE
        if self._chat.loaded:
            return AiStatus.READY
        if self._warming is not None and not self._warming.done():
            return AiStatus.WARMING
        return AiStatus.COLD

    @property
    def waiting(self) -> int:
        """How many calls are queued for a slot."""
        return self._slots.waiting

    # -- one reply ---------------------------------------------------------------

    async def complete(self, request: AiRequest) -> AiResult:
        """The whole reply at once.

        Raises AiUnavailableError, or one of its kinds, unless the request
        carries a fallback, in which case that is returned.
        """
        started = self._clock()

        async def attempt(model: str) -> str:
            async with asyncio.timeout(request.timeout or self._limits.request_timeout):
                return await self._client.complete(
                    model, request.messages, max_tokens=request.max_tokens
                )

        try:
            async with self._slot(request):
                text, model, attempts = await self._with_retries(request, attempt)
        except AiUnavailableError as exc:
            self._log(request, started, outcome=exc.code)
            if request.fallback is None:
                raise
            return AiResult(text=request.fallback, model=None, attempts=0, fallback=True)
        self._log(request, started, outcome="ok", model=model, attempts=attempts)
        return AiResult(text=text, model=model, attempts=attempts)

    # -- embeddings -------------------------------------------------------------

    async def embed(
        self,
        texts: Sequence[str],
        *,
        purpose: str,
        priority: Priority = Priority.INTERACTIVE,
        model: str | None = None,
        attempt_timeout: float | None = None,
        max_attempts: int | None = None,
        queue_timeout: float | None = None,
    ) -> list[list[float]]:
        """One vector per text, in the order given.

        Raises AiUnavailableError. There is no fallback model here: vectors
        from two models cannot be compared, so one from the wrong model is
        worse than none.
        """
        model = model or self._embedding_model
        if model is None:
            raise AiRejectedError("No embedding model is configured.", {})
        request = AiRequest(
            messages=(),
            purpose=purpose,
            priority=priority,
            model=model,
            timeout=attempt_timeout,
            max_attempts=max_attempts,
            queue_timeout=queue_timeout,
        )
        started = self._clock()

        async def attempt(model: str) -> list[list[float]]:
            async with asyncio.timeout(request.timeout or self._limits.request_timeout):
                vectors = await self._client.embed(model, texts)
            if len(vectors) != len(texts):
                # Vectors are paired to texts by position, so a short reply
                # would misalign every one after the gap.
                raise ValueError(f"{len(vectors)} vectors for {len(texts)} texts")
            return vectors

        try:
            async with self._slot(request):
                vectors, _, attempts = await self._with_retries(request, attempt, chat=False)
        except AiUnavailableError as exc:
            self._log(request, started, outcome=exc.code)
            raise
        self._log(request, started, outcome="ok", model=model, attempts=attempts)
        return vectors

    # -- a reply as it is written ---------------------------------------------------

    @contextlib.asynccontextmanager
    async def stream(self, request: AiRequest) -> AsyncIterator[AiStream]:
        """A reply delivered as the model writes it.

            async with gateway.stream(request) as reply:
                async for text in reply:
                    ...

        Leaving the block stops the model and frees the slot, however the
        block is left. The request waits for its slot inside the block, so
        the first piece may take as long as the queue does.
        """
        reply = AiStream()
        task = asyncio.create_task(
            self._produce(reply, request), name=f"ai-stream-{request.purpose}"
        )
        reply._task = task
        self._streams.add(task)
        task.add_done_callback(self._streams.discard)
        task.add_done_callback(lambda _: reply._finish())
        try:
            yield reply
        finally:
            if not task.done():
                task.cancel()
                # wait() rather than await: the task's own cancellation must
                # not be mistaken for the caller's.
                await asyncio.wait({task})

    async def _produce(self, reply: AiStream, request: AiRequest) -> None:
        started = self._clock()
        error: Exception | None = None

        async def attempt(model: str) -> None:
            delivered = False
            wait = self._limits.first_token_timeout
            try:
                pieces = self._client.stream(model, request.messages, max_tokens=request.max_tokens)
                async with contextlib.aclosing(pieces):
                    source = aiter(pieces)
                    while True:
                        try:
                            async with asyncio.timeout(wait):
                                text = await anext(source)
                        except StopAsyncIteration:
                            return
                        delivered = True
                        wait = self._limits.stream_idle_timeout
                        reply.model = model
                        reply._deliver(text)
            except (ModelUnreachableError, TimeoutError) as exc:
                if delivered:
                    # The reader has part of a reply. Starting again would
                    # repeat it, so the stream ends here and says so.
                    raise AiInterruptedError(
                        "The reply was interrupted. Ask again to see all of it.", {}
                    ) from exc
                raise

        try:
            async with self._slot(request):
                # Timed from the slot, not from the request: the wait for a
                # slot has a limit of its own, and a reply that queued for a
                # while is owed as long to be written as any other.
                try:
                    async with asyncio.timeout(self._limits.stream_timeout):
                        _, _, reply.attempts = await self._with_retries(request, attempt)
                except TimeoutError:
                    if not reply.text:
                        raise AiUnavailableError(
                            "The assistant took too long to answer. Try again shortly.", {}
                        ) from None
                    raise AiInterruptedError(
                        "The reply was interrupted. Ask again to see all of it.", {}
                    ) from None
        except AiUnavailableError as exc:
            if request.fallback is not None and not reply.text:
                reply.fallback = True
                reply._deliver(request.fallback)
            else:
                error = exc
            self._log(request, started, outcome=exc.code)
        except asyncio.CancelledError:
            self._log(request, started, outcome="cancelled")
            raise
        except Exception:
            log.exception("stream for %s failed unexpectedly", request.purpose)
            error = AiUnavailableError("The assistant is unavailable. Try again shortly.", {})
        else:
            self._log(request, started, outcome="ok", model=reply.model, attempts=reply.attempts)
        finally:
            reply._finish(error)

    # -- shared machinery ------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def _slot(self, request: AiRequest) -> AsyncIterator[None]:
        if self._closed:
            raise AiUnavailableError("The assistant is stopping. Try again shortly.", {})
        if self._breaker.refusing:
            # Refused before queueing: waiting for a slot only to be told the
            # model is down would hold the caller for nothing.
            raise AiUnavailableError("The assistant is unavailable. Try again shortly.", {})
        await self._slots.acquire(
            request.priority, request.queue_timeout or self._limits.queue_timeout
        )
        try:
            yield
        finally:
            self._slots.release()

    async def _with_retries(
        self, request: AiRequest, attempt: Callable[[str], Awaitable[T]], *, chat: bool = True
    ) -> tuple[T, str, int]:
        """Run `attempt` until it works, on the request's model and then the
        fallback model. Returns its value, the model that produced it and how
        many attempts were made. `chat` is false for embeddings, which have
        no fallback model and say nothing about whether the chat model is
        loaded."""
        models = [request.model or self._model]
        if chat and self._fallback_model and self._fallback_model not in models:
            models.append(self._fallback_model)
        attempts = 0
        last: BaseException | None = None

        for position, model in enumerate(models):
            # The fallback model gets one go: it is the way out, not a second
            # round of the same waiting.
            tries = (request.max_attempts or self._limits.max_attempts) if position == 0 else 1
            for attempt_number in range(tries):
                if not self._breaker.allow():
                    raise AiUnavailableError(
                        "The assistant is unavailable. Try again shortly.", {}
                    ) from last
                attempts += 1
                try:
                    value = await attempt(model)
                except ModelRejectedError as exc:
                    # The server answered, so it is up. The request is at fault.
                    self._breaker.success()
                    raise AiRejectedError(
                        "The assistant could not process that request.", {}
                    ) from exc
                except AiInterruptedError:
                    self._breaker.failure()
                    raise
                except (ModelUnreachableError, TimeoutError) as exc:
                    last = exc
                    retryable = not isinstance(exc, ModelUnreachableError) or exc.retry
                    if retryable:
                        self._breaker.failure()
                    else:
                        self._breaker.abandon()
                    log.warning(
                        "%s: attempt %d on %s failed: %s",
                        request.purpose,
                        attempts,
                        model,
                        type(exc).__name__ if isinstance(exc, TimeoutError) else exc,
                    )
                    if not retryable:
                        break
                    if attempt_number + 1 < tries:
                        await asyncio.sleep(self._pause(attempt_number))
                except Exception as exc:
                    # A reply the client could not read, or a bug in it. The
                    # caller is still owed AiUnavailableError or its fallback,
                    # and the same reply would break a second attempt too.
                    self._breaker.abandon()
                    log.exception("%s: attempt %d on %s broke", request.purpose, attempts, model)
                    raise AiUnavailableError(
                        "The assistant is unavailable. Try again shortly.", {}
                    ) from exc
                except BaseException:
                    self._breaker.abandon()
                    raise
                else:
                    self._breaker.success()
                    for warmth in (self._chat, self._embedder):
                        if warmth is not None and warmth.model == model:
                            warmth.answered(self._clock())
                    return value, model, attempts

        raise AiUnavailableError("The assistant is unavailable. Try again shortly.", {}) from last

    def _pause(self, attempt_number: int) -> float:
        # Jittered, so calls that failed together do not come back together.
        return self._limits.retry_pause * (2**attempt_number) * random.uniform(0.5, 1.0)

    def _log(
        self,
        request: AiRequest,
        started: float,
        *,
        outcome: str,
        model: str | None = None,
        attempts: int = 0,
    ) -> None:
        log.info(
            "%s priority=%s outcome=%s model=%s attempts=%d seconds=%.2f waiting=%d",
            request.purpose,
            request.priority.name.lower(),
            outcome,
            model or "-",
            attempts,
            self._clock() - started,
            self._slots.waiting,
        )

    # -- warm-up and shutdown ---------------------------------------------------------

    def start(self, *, warm_up: bool = True) -> None:
        """Accept calls, and begin loading the model in the background.
        Returns at once, so a model server that is slow or absent never holds
        up startup."""
        self._closed = False
        if warm_up and (self._warming is None or self._warming.done()):
            self._warming = asyncio.create_task(self._stay_warm(), name="ai-warm-up")

    async def _stay_warm(self) -> None:
        """Load the models, then keep them loaded for as long as the process
        runs.

        The server drops a model that has been idle for a few minutes, and the
        next student would wait out the whole load. A model that has answered
        recently is left alone: a busy class keeps it loaded by itself.
        """
        await self.warm_up()
        interval = self._limits.keep_warm_interval
        if interval <= 0:
            return
        while True:
            now = self._clock()
            kept = [warmth for warmth in (self._chat, self._embedder) if warmth is not None]
            wait = min(warmth.due(interval) for warmth in kept) - now
            if wait > 0:
                await asyncio.sleep(wait)
                continue
            for warmth in kept:
                if warmth.due(interval) > now:
                    continue
                # Marked as asked whether or not it answers, so a model that
                # is down is tried once an interval and not in a tight loop.
                warmth.asked = now
                # Only a model that has answered before. One that never has
                # is absent, and asking it would only fill the log.
                if warmth.loaded:
                    await self._ask_to_stay(warmth)

    async def _ask_to_stay(self, warmth: _Warmth) -> None:
        """One word from a model, through the queue like any other call, so
        it never runs ahead of someone who is waiting."""
        with contextlib.suppress(AiUnavailableError):
            if warmth is self._chat:
                await self.complete(
                    AiRequest(
                        messages=WARMUP_MESSAGES,
                        purpose="keep-warm",
                        priority=Priority.BACKGROUND,
                        max_tokens=1,
                        max_attempts=1,
                    )
                )
            else:
                await self.embed(
                    [WARMUP_TEXT], purpose="keep-warm", priority=Priority.BACKGROUND, max_attempts=1
                )

    async def warm_up(self) -> None:
        """Ask each model for one word, so its weights are in memory before a
        student asks for a paragraph. Without this the first request after a
        start pays the load time, which can outlast its own deadline."""
        await self._load(
            self._chat,
            lambda: self._client.complete(self._model, WARMUP_MESSAGES, max_tokens=1),
        )
        if self._embedder is not None:
            embedder = self._embedder
            await self._load(embedder, lambda: self._client.embed(embedder.model, [WARMUP_TEXT]))

    async def _load(self, warmth: _Warmth, ask: Callable[[], Awaitable[object]]) -> None:
        pause = WARMUP_FIRST_PAUSE_SECONDS
        for attempt_number in range(1, WARMUP_ATTEMPTS + 1):
            try:
                async with asyncio.timeout(self._limits.warmup_timeout):
                    await ask()
            except ModelRejectedError as exc:
                log.warning(
                    "warm-up of %s was refused and will not be retried: %s", warmth.model, exc
                )
                return
            except (ModelUnreachableError, TimeoutError) as exc:
                log.info(
                    "warm-up of %s, attempt %d of %d, failed: %s",
                    warmth.model,
                    attempt_number,
                    WARMUP_ATTEMPTS,
                    type(exc).__name__ if isinstance(exc, TimeoutError) else exc,
                )
                if isinstance(exc, ModelUnreachableError) and not exc.retry:
                    break
                if attempt_number < WARMUP_ATTEMPTS:
                    await asyncio.sleep(pause)
                    pause = min(pause * 2, WARMUP_MAX_PAUSE_SECONDS)
            else:
                warmth.answered(self._clock())
                log.info("model %s is loaded", warmth.model)
                return
        log.warning(
            "model %s could not be warmed up, so the first request will wait for it to load",
            warmth.model,
        )

    async def shutdown(self) -> None:
        """Refuse new calls and stop the ones in flight."""
        self._closed = True
        tasks = set(self._streams)
        if self._warming is not None:
            tasks.add(self._warming)
        pending = {task for task in tasks if not task.done()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending)

    # -- for code written against the OpenAI client ------------------------------------

    def chat_client(
        self,
        purpose: str,
        *,
        priority: Priority = Priority.BACKGROUND,
        timeout: float | None = None,
        max_attempts: int | None = None,
        queue_timeout: float | None = None,
    ) -> SimpleNamespace:
        """An object with the one OpenAI method the question generator uses,
        `chat.completions.create(model=..., messages=...)`, routed through
        the gateway. It lets that code keep its shape while its calls take
        their turn with everyone else's."""
        gateway = self

        async def create(*, model: str, messages: Sequence[Message]) -> SimpleNamespace:
            result = await gateway.complete(
                AiRequest(
                    messages=messages,
                    purpose=purpose,
                    priority=priority,
                    model=model,
                    timeout=timeout,
                    max_attempts=max_attempts,
                    queue_timeout=queue_timeout,
                )
            )
            message = SimpleNamespace(content=result.text)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], model=result.model)

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class GatewayEmbeddingClient:
    """`embed(texts)` through the gateway, for the embedder and the retriever,
    which were written against a client with that one method."""

    def __init__(
        self,
        gateway: AiGateway,
        purpose: str,
        *,
        priority: Priority = Priority.INTERACTIVE,
        timeout: float | None = None,
        max_attempts: int | None = None,
        queue_timeout: float | None = None,
    ) -> None:
        self._gateway = gateway
        self._options = {
            "purpose": purpose,
            "priority": priority,
            "attempt_timeout": timeout,
            "max_attempts": max_attempts,
            "queue_timeout": queue_timeout,
        }

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._gateway.embed(texts, **self._options)


@lru_cache
def get_ai_gateway() -> AiGateway:
    """The process's gateway, pointed at the configured model server."""
    settings = get_settings()
    client = AsyncOpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",
        # The gateway times each attempt and decides what is retried. Left on,
        # the client's own retries would multiply both.
        timeout=None,
        max_retries=0,
    )
    return AiGateway(
        OpenAIModelClient(client),
        settings.ollama_model,
        AiLimits.from_settings(settings),
        fallback_model=settings.ollama_fallback_model,
        embedding_model=settings.embedding_model,
    )
