"""The gateway every model call goes through.

Owner: General CS, Phase 5.

The deliverable is that AI work does not block the live-session service. So
these check what the gateway owes its callers when the model is slow, down
or abandoned: a bounded slot served by priority, a deadline, another try, a
way out, and cancellation that reaches the model and frees the slot.

No test here talks to a model. FakeModel plays one, and does what each test
scripts for it.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence

import httpx
import openai
import pytest

from app.core.config import Settings
from app.services import ai_gateway as gateway_module
from app.services import uploads as uploads_module
from app.services.ai_gateway import (
    AiBusyError,
    AiGateway,
    AiInterruptedError,
    AiLimits,
    AiRejectedError,
    AiRequest,
    AiStatus,
    AiUnavailableError,
    GatewayEmbeddingClient,
    Message,
    ModelRejectedError,
    ModelUnreachableError,
    OpenAIModelClient,
    Priority,
    _Slots,
)

WAIT_SECONDS = 5.0
HANG = object()

# Short enough that a test waiting one out stays fast, long enough that a
# loaded CI machine does not trip one by accident.
QUICK = AiLimits(
    max_concurrency=1,
    queue_limit=8,
    queue_timeout=WAIT_SECONDS,
    request_timeout=WAIT_SECONDS,
    first_token_timeout=WAIT_SECONDS,
    stream_idle_timeout=WAIT_SECONDS,
    stream_timeout=WAIT_SECONDS,
    max_attempts=3,
    retry_pause=0.0,
    breaker_failures=100,
    breaker_cooldown=30.0,
    warmup_timeout=WAIT_SECONDS,
)


def _limits(**changes: float) -> AiLimits:
    return AiLimits(**{**QUICK.__dict__, **changes})


class FakeModel:
    """A model that does what the test scripts, one step per call.

    A step is text to return, an exception to raise, HANG to never answer, or
    for a stream a list of those, delivered in order. With nothing scripted a
    call answers "ok", after waiting for `hold` when the test has set one.
    """

    def __init__(self, *steps: object) -> None:
        self.steps: deque[object] = deque(steps)
        self.calls: list[tuple[str, str]] = []
        self.active = 0
        self.peak = 0
        self.closed_streams = 0
        self.hold: asyncio.Event | None = None

    def _begin(self, model: str, messages: Sequence[Message]) -> object:
        self.calls.append((model, messages[-1]["content"]))
        self.active += 1
        self.peak = max(self.peak, self.active)
        return self.steps.popleft() if self.steps else None

    async def complete(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> str:
        step = self._begin(model, messages)
        try:
            if step is None:
                if self.hold is not None:
                    await self.hold.wait()
                return "ok"
            return await _play(step)
        finally:
            self.active -= 1

    async def stream(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> AsyncIterator[str]:
        step = self._begin(model, messages)
        try:
            for piece in step if isinstance(step, list) else [step or "ok"]:
                yield await _play(piece)
        finally:
            self.active -= 1
            self.closed_streams += 1

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        step = self._begin(model, [{"content": " | ".join(texts)}])
        try:
            if step is None:
                if self.hold is not None:
                    await self.hold.wait()
                return [[float(len(text))] for text in texts]
            if isinstance(step, list):
                return step
            await _play(step)
            raise AssertionError("an embed step is vectors, an error or HANG")
        finally:
            self.active -= 1


async def _play(step: object) -> str:
    if step is HANG:
        await asyncio.Event().wait()
    if isinstance(step, BaseException):
        raise step
    return str(step)


def _ask(content: str = "question", **fields: object) -> AiRequest:
    return AiRequest(messages=[{"role": "user", "content": content}], purpose="test", **fields)


async def _until(condition: Callable[[], bool]) -> None:
    """Let other tasks run until `condition` holds, failing if it never does."""
    async with asyncio.timeout(WAIT_SECONDS):
        while not condition():  # noqa: ASYNC110 - the condition is state, not an event
            await asyncio.sleep(0)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# -- one reply ---------------------------------------------------------------------


async def test_a_reply_names_the_model_that_wrote_it() -> None:
    model = FakeModel("Photosynthesis makes glucose.")
    gateway = AiGateway(model, "qwen2.5", QUICK)

    result = await gateway.complete(_ask("What does photosynthesis make?"))

    assert (result.text, result.model, result.attempts, result.fallback) == (
        "Photosynthesis makes glucose.",
        "qwen2.5",
        1,
        False,
    )
    assert model.calls == [("qwen2.5", "What does photosynthesis make?")]


async def test_a_slow_model_does_not_stop_the_event_loop() -> None:
    """The deliverable. While the model is thinking, everything else on the
    process, which is every live session, keeps being served."""
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", QUICK)
    served = 0

    async def live_session() -> None:
        nonlocal served
        while True:
            await asyncio.sleep(0)
            served += 1

    session = asyncio.create_task(live_session())
    call = asyncio.create_task(gateway.complete(_ask()))
    await _until(lambda: model.active == 1 and served > 100)
    model.hold.set()

    assert (await call).text == "ok"
    session.cancel()


# -- slots and the queue -------------------------------------------------------------


async def test_no_more_calls_reach_the_model_than_there_are_slots() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", _limits(max_concurrency=2))

    calls = [asyncio.create_task(gateway.complete(_ask(str(n)))) for n in range(6)]
    await _until(lambda: model.active == 2 and gateway.waiting == 4)
    model.hold.set()
    await asyncio.gather(*calls)

    assert model.peak == 2
    assert gateway.waiting == 0


async def test_waiting_calls_are_served_by_priority_then_by_arrival() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", QUICK)
    first = asyncio.create_task(gateway.complete(_ask("first")))
    await _until(lambda: model.active == 1)

    queued = []
    for content, priority in [
        ("upload", Priority.BACKGROUND),
        ("lecturer", Priority.INTERACTIVE),
        ("student one", Priority.LIVE),
        ("student two", Priority.LIVE),
    ]:
        queued.append(asyncio.create_task(gateway.complete(_ask(content, priority=priority))))
        await _until(lambda: gateway.waiting == len(queued))
    model.hold.set()
    await asyncio.gather(first, *queued)

    assert [content for _, content in model.calls] == [
        "first",
        "student one",
        "student two",
        "lecturer",
        "upload",
    ]


async def test_a_full_queue_refuses_at_once() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", _limits(queue_limit=1))
    running = asyncio.create_task(gateway.complete(_ask("running")))
    await _until(lambda: model.active == 1)
    waiting = asyncio.create_task(gateway.complete(_ask("waiting")))
    await _until(lambda: gateway.waiting == 1)

    with pytest.raises(AiBusyError):
        await gateway.complete(_ask("one too many"))

    model.hold.set()
    await asyncio.gather(running, waiting)
    assert [content for _, content in model.calls] == ["running", "waiting"]


async def test_a_call_that_waits_too_long_gives_up_and_keeps_no_place() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", QUICK)
    running = asyncio.create_task(gateway.complete(_ask("running")))
    await _until(lambda: model.active == 1)

    with pytest.raises(AiBusyError):
        await gateway.complete(_ask("impatient", queue_timeout=0.01))

    assert gateway.waiting == 0
    model.hold.set()
    await running
    assert (await gateway.complete(_ask("next"))).text == "ok"
    assert [content for _, content in model.calls] == ["running", "next"]


async def test_cancelling_a_queued_call_never_reaches_the_model() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", QUICK)
    running = asyncio.create_task(gateway.complete(_ask("running")))
    await _until(lambda: model.active == 1)
    abandoned = asyncio.create_task(gateway.complete(_ask("abandoned")))
    kept = asyncio.create_task(gateway.complete(_ask("kept")))
    await _until(lambda: gateway.waiting == 2)

    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned
    model.hold.set()
    await asyncio.gather(running, kept)

    assert [content for _, content in model.calls] == ["running", "kept"]
    assert gateway.waiting == 0


async def test_cancelling_a_running_call_frees_its_slot() -> None:
    model = FakeModel(HANG)
    gateway = AiGateway(model, "m", QUICK)
    call = asyncio.create_task(gateway.complete(_ask("abandoned")))
    await _until(lambda: model.active == 1)

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call

    assert model.active == 0
    assert (await gateway.complete(_ask("next"))).text == "ok"


async def test_a_slot_handed_to_a_call_as_it_is_cancelled_is_passed_on() -> None:
    """The slot is granted and the waiter cancelled in the same turn of the
    loop. The slot must go to the next waiter, not vanish with this one."""
    slots = _Slots(limit=1, queue_limit=8)
    await slots.acquire(Priority.LIVE, WAIT_SECONDS)
    cancelled = asyncio.create_task(slots.acquire(Priority.LIVE, WAIT_SECONDS))
    await _until(lambda: slots.waiting == 1)
    next_in_line = asyncio.create_task(slots.acquire(Priority.LIVE, WAIT_SECONDS))
    await _until(lambda: slots.waiting == 2)

    # No await between the two: the grant has not been seen when the cancel lands.
    slots.release()
    cancelled.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await asyncio.wait_for(next_in_line, WAIT_SECONDS)
    assert slots.waiting == 0


async def test_a_slot_handed_to_a_call_as_it_times_out_is_passed_on() -> None:
    slots = _Slots(limit=1, queue_limit=8)
    await slots.acquire(Priority.LIVE, WAIT_SECONDS)
    impatient = asyncio.create_task(slots.acquire(Priority.LIVE, 0.01))
    await _until(lambda: slots.waiting == 1)
    next_in_line = asyncio.create_task(slots.acquire(Priority.LIVE, WAIT_SECONDS))
    await _until(lambda: slots.waiting == 2)

    with pytest.raises(AiBusyError):
        await impatient
    slots.release()

    await asyncio.wait_for(next_in_line, WAIT_SECONDS)
    assert slots.waiting == 0


# -- deadlines, retries and the way out -------------------------------------------------


async def test_an_attempt_that_runs_out_of_time_is_tried_again() -> None:
    model = FakeModel(HANG, "second time lucky")
    gateway = AiGateway(model, "m", QUICK)

    result = await gateway.complete(_ask(timeout=0.01))

    assert (result.text, result.attempts) == ("second time lucky", 2)
    assert model.active == 0


async def test_an_unreachable_model_is_tried_a_set_number_of_times() -> None:
    model = FakeModel(*[ModelUnreachableError("down")] * 5)
    gateway = AiGateway(model, "m", QUICK)

    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())

    assert len(model.calls) == QUICK.max_attempts
    assert (await gateway.complete(_ask(max_attempts=1, fallback="later"))).fallback is True
    assert len(model.calls) == QUICK.max_attempts + 1


async def test_a_fallback_is_returned_in_place_of_an_error() -> None:
    model = FakeModel(*[ModelUnreachableError("down")] * 3)
    gateway = AiGateway(model, "m", QUICK)

    result = await gateway.complete(_ask(fallback="The assistant is unavailable."))

    assert (result.text, result.model, result.fallback) == (
        "The assistant is unavailable.",
        None,
        True,
    )


async def test_a_request_the_model_refuses_is_not_sent_again() -> None:
    model = FakeModel(ModelRejectedError("HTTP 400"), "never asked for")
    gateway = AiGateway(model, "m", QUICK)

    with pytest.raises(AiRejectedError):
        await gateway.complete(_ask())

    assert len(model.calls) == 1


async def test_the_fallback_model_answers_when_the_first_cannot() -> None:
    model = FakeModel(*[ModelUnreachableError("overloaded")] * 3, "from the small model")
    gateway = AiGateway(model, "large", QUICK, fallback_model="small")

    result = await gateway.complete(_ask())

    assert (result.text, result.model, result.attempts) == ("from the small model", "small", 4)
    assert [name for name, _ in model.calls] == ["large", "large", "large", "small"]


async def test_the_fallback_model_is_asked_once() -> None:
    model = FakeModel(*[ModelUnreachableError("down")] * 6)
    gateway = AiGateway(model, "large", QUICK, fallback_model="small")

    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())

    assert [name for name, _ in model.calls] == ["large", "large", "large", "small"]


async def test_a_model_that_is_not_installed_is_asked_once() -> None:
    missing = ModelUnreachableError("the model is not installed", retry=False)
    model = FakeModel(missing, "from the small model")
    gateway = AiGateway(model, "large", QUICK, fallback_model="small")

    result = await gateway.complete(_ask())

    assert [name for name, _ in model.calls] == ["large", "small"]
    assert result.model == "small"


async def test_a_model_that_keeps_failing_is_left_alone_for_a_while() -> None:
    clock = Clock()
    limits = _limits(max_attempts=1, breaker_failures=2, breaker_cooldown=30.0)
    model = FakeModel(ModelUnreachableError("down"), ModelUnreachableError("down"))
    gateway = AiGateway(model, "m", limits, clock=clock)
    for _ in range(2):
        with pytest.raises(AiUnavailableError):
            await gateway.complete(_ask())

    # Open: refused without the model being asked.
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())
    assert len(model.calls) == 2
    assert gateway.status is AiStatus.UNAVAILABLE

    # After the cool-down one call is let through, and its success closes it.
    clock.now = 31.0
    assert (await gateway.complete(_ask())).text == "ok"
    assert (await gateway.complete(_ask())).text == "ok"
    assert len(model.calls) == 4


async def test_a_failed_trial_keeps_the_model_left_alone() -> None:
    clock = Clock()
    limits = _limits(max_attempts=1, breaker_failures=1, breaker_cooldown=30.0)
    model = FakeModel(ModelUnreachableError("down"), ModelUnreachableError("still down"))
    gateway = AiGateway(model, "m", limits, clock=clock)
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())

    clock.now = 31.0
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())

    assert len(model.calls) == 2


@pytest.mark.parametrize("slots", [1, 2])
async def test_only_one_call_tries_a_model_that_was_failing(slots: int) -> None:
    """While the trial is out, everyone else is refused at once: not sent to
    the model with a slot to spare, and not left queueing with none."""
    clock = Clock()
    limits = _limits(
        max_concurrency=slots, max_attempts=1, breaker_failures=1, breaker_cooldown=30.0
    )
    model = FakeModel(ModelUnreachableError("down"), HANG)
    gateway = AiGateway(model, "m", limits, clock=clock)
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())
    clock.now = 31.0
    trial = asyncio.create_task(gateway.complete(_ask("trial")))
    await _until(lambda: model.active == 1)

    with pytest.raises(AiUnavailableError) as refused:
        await asyncio.wait_for(gateway.complete(_ask("everyone else")), 1.0)

    assert type(refused.value) is AiUnavailableError
    assert gateway.waiting == 0
    assert [content for _, content in model.calls] == ["question", "trial"]
    trial.cancel()


async def test_a_cancelled_trial_does_not_leave_the_model_shut_out() -> None:
    clock = Clock()
    limits = _limits(max_attempts=1, breaker_failures=1, breaker_cooldown=30.0)
    model = FakeModel(ModelUnreachableError("down"), HANG)
    gateway = AiGateway(model, "m", limits, clock=clock)
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())
    clock.now = 31.0
    trial = asyncio.create_task(gateway.complete(_ask()))
    await _until(lambda: model.active == 1)

    trial.cancel()
    with pytest.raises(asyncio.CancelledError):
        await trial

    assert (await gateway.complete(_ask())).text == "ok"


async def test_a_refusal_does_not_count_against_the_model() -> None:
    limits = _limits(breaker_failures=1)
    model = FakeModel(ModelRejectedError("HTTP 400"))
    gateway = AiGateway(model, "m", limits)
    with pytest.raises(AiRejectedError):
        await gateway.complete(_ask())

    assert (await gateway.complete(_ask())).text == "ok"


# -- embeddings ---------------------------------------------------------------------


async def test_embedding_returns_a_vector_for_each_text_in_order() -> None:
    model = FakeModel()
    gateway = AiGateway(model, "chat", QUICK, embedding_model="nomic-embed-text")

    vectors = await gateway.embed(["ab", "abcd", "a"], purpose="retrieval")

    assert vectors == [[2.0], [4.0], [1.0]]
    assert model.calls == [("nomic-embed-text", "ab | abcd | a")]


async def test_embedding_waits_its_turn_like_any_other_call() -> None:
    """A student's question is embedded before the material is searched, so
    in a live class embeddings are part of the load the queue exists for."""
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "chat", QUICK, embedding_model="embedder")
    running = asyncio.create_task(gateway.complete(_ask("running")))
    await _until(lambda: model.active == 1)

    upload = asyncio.create_task(
        gateway.embed(["deck"], purpose="material", priority=Priority.BACKGROUND)
    )
    await _until(lambda: gateway.waiting == 1)
    student = asyncio.create_task(
        gateway.embed(["question"], purpose="retrieval", priority=Priority.LIVE)
    )
    await _until(lambda: gateway.waiting == 2)
    model.hold.set()
    await asyncio.gather(running, upload, student)

    assert model.peak == 1
    assert [content for _, content in model.calls] == ["running", "question", "deck"]


async def test_embedding_is_tried_again_but_never_on_another_model() -> None:
    """Vectors from two models cannot be compared, so the fallback model,
    which rescues a reply, must stay out of it."""
    model = FakeModel(ModelUnreachableError("down"), [[0.5]])
    gateway = AiGateway(model, "chat", QUICK, fallback_model="small", embedding_model="embedder")

    assert await gateway.embed(["text"], purpose="retrieval") == [[0.5]]

    model.steps.extend([ModelUnreachableError("down")] * 3)
    with pytest.raises(AiUnavailableError):
        await gateway.embed(["text"], purpose="retrieval")
    assert {name for name, _ in model.calls} == {"embedder"}
    assert len(model.calls) == 2 + QUICK.max_attempts


async def test_a_reply_with_the_wrong_number_of_vectors_is_not_passed_on() -> None:
    model = FakeModel([[0.1]])
    gateway = AiGateway(model, "chat", QUICK, embedding_model="embedder")

    with pytest.raises(AiUnavailableError):
        await gateway.embed(["one", "two"], purpose="retrieval")

    assert model.active == 0


async def test_embedding_needs_a_model_to_be_named() -> None:
    gateway = AiGateway(FakeModel(), "chat", QUICK)

    with pytest.raises(AiRejectedError):
        await gateway.embed(["text"], purpose="retrieval")
    assert await gateway.embed(["text"], purpose="retrieval", model="embedder") == [[4.0]]


async def test_embedding_does_not_pass_for_the_chat_model_being_loaded() -> None:
    gateway = AiGateway(FakeModel(), "chat", QUICK, embedding_model="embedder")

    await gateway.embed(["text"], purpose="retrieval")

    assert gateway.status is AiStatus.COLD


async def test_the_embedders_client_goes_through_the_gateway() -> None:
    model = FakeModel()
    gateway = AiGateway(model, "chat", QUICK, embedding_model="embedder")
    client = GatewayEmbeddingClient(gateway, "retrieval", priority=Priority.LIVE)

    assert await client.embed(["question"]) == [[8.0]]
    assert model.calls == [("embedder", "question")]


# -- streams -----------------------------------------------------------------------


async def test_a_stream_delivers_the_reply_piece_by_piece() -> None:
    model = FakeModel(["Think ", "about ", "light."])
    gateway = AiGateway(model, "qwen2.5", QUICK)

    async with gateway.stream(_ask()) as reply:
        pieces = [text async for text in reply]

    assert pieces == ["Think ", "about ", "light."]
    assert (reply.text, reply.model, reply.attempts) == ("Think about light.", "qwen2.5", 1)
    assert (reply.cancelled, reply.fallback) == (False, False)
    assert model.active == 0


async def test_a_stream_that_never_starts_is_tried_again() -> None:
    model = FakeModel([ModelUnreachableError("down")], [HANG], ["Here ", "it is."])
    gateway = AiGateway(model, "m", _limits(first_token_timeout=0.01))

    async with gateway.stream(_ask()) as reply:
        pieces = [text async for text in reply]

    assert pieces == ["Here ", "it is."]
    assert reply.attempts == 3


async def test_a_stream_that_breaks_partway_is_not_started_again() -> None:
    """The reader already has "Think ". A second attempt would say it twice."""
    model = FakeModel(["Think ", ModelUnreachableError("dropped")], ["Think about light."])
    gateway = AiGateway(model, "m", QUICK)
    pieces = []

    async with gateway.stream(_ask(fallback="unavailable")) as reply:
        with pytest.raises(AiInterruptedError):
            async for text in reply:
                pieces.append(text)

    assert pieces == ["Think "]
    assert len(model.calls) == 1
    assert reply.fallback is False


async def test_a_stream_that_goes_quiet_is_ended() -> None:
    model = FakeModel(["Think ", HANG])
    gateway = AiGateway(model, "m", _limits(stream_idle_timeout=0.01))
    pieces = []

    async with gateway.stream(_ask()) as reply:
        with pytest.raises(AiInterruptedError):
            async for text in reply:
                pieces.append(text)

    assert pieces == ["Think "]
    assert (model.active, model.closed_streams) == (0, 1)


async def test_a_stream_may_not_run_for_ever() -> None:
    model = FakeModel([HANG])
    gateway = AiGateway(model, "m", _limits(stream_timeout=0.05))

    async with gateway.stream(_ask()) as reply:
        with pytest.raises(AiUnavailableError):
            async for _ in reply:
                pass

    assert model.active == 0
    assert (await gateway.complete(_ask())).text == "ok"


async def test_a_streams_time_limit_starts_when_it_reaches_the_model() -> None:
    """A reply that queued behind others is owed its full time to be written.
    The wait for a slot has its own limit."""
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", _limits(stream_timeout=0.2))
    running = asyncio.create_task(gateway.complete(_ask("running")))
    await _until(lambda: model.active == 1)

    async with gateway.stream(_ask("queued")) as reply:
        await _until(lambda: gateway.waiting == 1)
        # Longer in the queue than the whole reply is allowed to take.
        await asyncio.sleep(0.4)
        model.hold.set()
        pieces = [text async for text in reply]

    await running
    assert pieces == ["ok"]


async def test_a_stream_with_a_fallback_says_that_when_the_model_cannot() -> None:
    model = FakeModel(*[[ModelUnreachableError("down")]] * 3)
    gateway = AiGateway(model, "m", QUICK)

    async with gateway.stream(_ask(fallback="The assistant is unavailable.")) as reply:
        pieces = [text async for text in reply]

    assert pieces == ["The assistant is unavailable."]
    assert (reply.fallback, reply.model) == (True, None)


async def test_cancelling_a_stream_stops_the_model_and_frees_the_slot() -> None:
    model = FakeModel(["Think ", HANG])
    gateway = AiGateway(model, "m", QUICK)
    pieces = []

    async with gateway.stream(_ask()) as reply:
        async for text in reply:
            pieces.append(text)
            reply.cancel()

    assert pieces == ["Think "]
    assert reply.cancelled is True
    assert (model.active, model.closed_streams) == (0, 1)
    assert (await gateway.complete(_ask())).text == "ok"


async def test_leaving_a_stream_early_stops_the_model() -> None:
    model = FakeModel(["Think ", HANG])
    gateway = AiGateway(model, "m", QUICK)

    async with gateway.stream(_ask()) as reply:
        async for _ in reply:
            break

    assert (model.active, model.closed_streams) == (0, 1)
    assert (await gateway.complete(_ask())).text == "ok"


async def test_a_reader_that_is_cancelled_takes_its_stream_with_it() -> None:
    """A student closes the tab: the socket's task is cancelled mid-reply."""
    model = FakeModel(["Think ", HANG])
    gateway = AiGateway(model, "m", QUICK)
    reading = asyncio.Event()

    async def reader() -> None:
        async with gateway.stream(_ask()) as reply:
            async for _ in reply:
                reading.set()

    task = asyncio.create_task(reader())
    await reading.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (model.active, model.closed_streams) == (0, 1)
    assert (await gateway.complete(_ask())).text == "ok"


async def test_a_stream_cancelled_while_queued_never_reaches_the_model() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "m", QUICK)
    running = asyncio.create_task(gateway.complete(_ask("running")))
    await _until(lambda: model.active == 1)

    async with gateway.stream(_ask("abandoned")) as reply:
        await _until(lambda: gateway.waiting == 1)
        reply.cancel()
        assert [text async for text in reply] == []

    model.hold.set()
    await running
    assert [content for _, content in model.calls] == ["running"]
    assert gateway.waiting == 0


async def test_a_stream_cancelled_before_it_starts_still_ends() -> None:
    """Cancelled before its task has run a step, so nothing inside the task
    gets the chance to end the reply. The reader must not wait for ever."""
    model = FakeModel(["never sent"])
    gateway = AiGateway(model, "m", QUICK)

    async with gateway.stream(_ask()) as reply:
        reply.cancel()
        pieces = await asyncio.wait_for(_collect(reply), 1.0)

    assert pieces == []
    assert model.calls == []


async def test_a_stream_cut_off_by_shutdown_before_it_starts_still_ends() -> None:
    gateway = AiGateway(FakeModel(["never sent"]), "m", QUICK)

    async with gateway.stream(_ask()) as reply:
        await gateway.shutdown()
        pieces = await asyncio.wait_for(_collect(reply), 1.0)

    assert pieces == []


async def _collect(reply) -> list[str]:  # noqa: ANN001
    return [text async for text in reply]


async def test_a_model_client_that_breaks_is_an_unavailable_model_not_a_crash() -> None:
    """A reply the client cannot read, or a bug in the client. A caller that
    gave a fallback was promised text, whatever went wrong underneath."""
    model = FakeModel(IndexError("no choices"), [KeyError("delta")])
    gateway = AiGateway(model, "m", QUICK)

    result = await gateway.complete(_ask(fallback="unavailable"))
    async with gateway.stream(_ask(fallback="unavailable")) as reply:
        pieces = [text async for text in reply]

    assert (result.text, result.fallback) == ("unavailable", True)
    assert pieces == ["unavailable"]
    # Not worth a second attempt: the same reply would break the same way.
    assert len(model.calls) == 2
    assert model.active == 0


# -- everything at once ----------------------------------------------------------------


class _UnrulyModel:
    """A model that answers, fails, breaks or stalls as the dice fall."""

    def __init__(self, dice: random.Random) -> None:
        self._dice = dice
        self.active = 0
        self.peak = 0

    async def _behave(self) -> None:
        roll = self._dice.random()
        # Turns of the loop, not time: a timer is too coarse on Windows to
        # finish inside the short deadlines this test runs with.
        for _ in range(self._dice.randint(0, 5)):
            await asyncio.sleep(0)
        if roll < 0.15:
            raise ModelUnreachableError("down")
        if roll < 0.20:
            raise ModelRejectedError("HTTP 400")
        if roll < 0.25:
            raise RuntimeError("the client broke")
        if roll < 0.35:
            await asyncio.Event().wait()

    async def complete(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> str:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await self._behave()
            return "ok"
        finally:
            self.active -= 1

    async def stream(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> AsyncIterator[str]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            for _ in range(self._dice.randint(1, 4)):
                await self._behave()
                yield "piece "
        finally:
            self.active -= 1

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await self._behave()
            return [[1.0] for _ in texts]
        finally:
            self.active -= 1


@pytest.mark.parametrize("seed", range(5))
async def test_no_slot_is_lost_whatever_callers_and_the_model_do(seed: int) -> None:
    """Four hundred calls of every kind against a model that fails, breaks
    and stalls, with callers that cancel, give up and walk away mid-reply.
    When the dust settles every slot must be free and nobody left waiting:
    a slot leaked on any path would, in a long class, end with no calls
    reaching the model at all."""
    dice = random.Random(seed)
    model = _UnrulyModel(dice)
    limits = _limits(
        max_concurrency=3,
        queue_limit=20,
        queue_timeout=0.3,
        request_timeout=0.05,
        first_token_timeout=0.05,
        stream_idle_timeout=0.05,
        stream_timeout=0.3,
        max_attempts=2,
        breaker_failures=4,
        breaker_cooldown=0.01,
    )
    gateway = AiGateway(model, "m", limits, fallback_model="small", embedding_model="embedder")

    async def caller() -> None:
        priority = dice.choice(list(Priority))
        fallback = dice.choice([None, "fallback"])
        kind = dice.choice(["complete", "stream", "embed"])
        await asyncio.sleep(dice.uniform(0, 0.02))
        with contextlib.suppress(AiUnavailableError):
            if kind == "complete":
                await gateway.complete(_ask(priority=priority, fallback=fallback))
            elif kind == "embed":
                await gateway.embed(["text"], purpose="fuzz", priority=priority)
            else:
                leave_after = dice.choice([None, 1, 2])
                cancel_after = dice.choice([None, 1])
                async with gateway.stream(_ask(priority=priority, fallback=fallback)) as reply:
                    seen = 0
                    async for _ in reply:
                        seen += 1
                        if seen == cancel_after:
                            reply.cancel()
                        if seen == leave_after:
                            break

    tasks = [asyncio.create_task(caller()) for _ in range(400)]
    for task in dice.sample(tasks, 80):
        asyncio.get_running_loop().call_later(dice.uniform(0, 0.04), task.cancel)
    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 30)

    unexpected = [
        result
        for result in results
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
    ]
    assert unexpected == []
    await _until(lambda: not gateway._streams)
    assert model.peak <= limits.max_concurrency
    assert (model.active, gateway.waiting) == (0, 0)
    assert gateway._slots._free == limits.max_concurrency
    assert all(granted.done() for _, _, granted in gateway._slots._waiters)


# -- warm-up and shutdown ---------------------------------------------------------------


async def test_warm_up_loads_the_model_without_holding_up_startup() -> None:
    model = FakeModel()
    model.hold = asyncio.Event()
    gateway = AiGateway(model, "qwen2.5", QUICK)
    assert gateway.status is AiStatus.COLD

    gateway.start()

    # start() returned while the model is still loading.
    await _until(lambda: model.active == 1)
    assert gateway.status is AiStatus.WARMING
    model.hold.set()
    await _until(lambda: gateway.status is AiStatus.READY)
    assert model.calls == [("qwen2.5", "Reply with OK.")]
    await gateway.shutdown()


async def test_warm_up_tries_again_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_module, "WARMUP_FIRST_PAUSE_SECONDS", 0.0)
    attempts = gateway_module.WARMUP_ATTEMPTS
    model = FakeModel(*[ModelUnreachableError("no server")] * attempts)
    gateway = AiGateway(model, "m", QUICK)

    await gateway.warm_up()

    assert len(model.calls) == attempts
    assert gateway.status is AiStatus.COLD
    # A failed warm-up is not held against the model.
    assert (await gateway.complete(_ask())).text == "ok"


async def test_an_idle_model_is_kept_loaded() -> None:
    """The server unloads a model nobody has used for a few minutes. Asking
    for one word before then is what stops the next student waiting out a
    load."""
    model = FakeModel()
    gateway = AiGateway(model, "m", _limits(keep_warm_interval=0.02))

    gateway.start()
    await _until(lambda: len(model.calls) >= 3)
    await gateway.shutdown()

    assert {content for _, content in model.calls} == {"Reply with OK."}


async def test_a_model_in_use_is_not_asked_to_stay_loaded() -> None:
    clock = Clock()
    model = FakeModel()
    gateway = AiGateway(model, "m", _limits(keep_warm_interval=0.05), clock=clock)
    gateway.start()
    await _until(lambda: gateway.status is AiStatus.READY)

    # The clock never reaches the interval, as it never does in a busy class.
    await asyncio.sleep(0.2)
    await gateway.shutdown()

    assert len(model.calls) == 1


async def test_a_model_that_never_answered_is_not_asked_to_stay_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway_module, "WARMUP_FIRST_PAUSE_SECONDS", 0.0)
    attempts = gateway_module.WARMUP_ATTEMPTS
    model = FakeModel(*[ModelUnreachableError("no server")] * attempts)
    gateway = AiGateway(model, "m", _limits(keep_warm_interval=0.01))

    gateway.start()
    await _until(lambda: len(model.calls) == attempts)
    await asyncio.sleep(0.1)
    await gateway.shutdown()

    assert len(model.calls) == attempts


async def test_keeping_the_model_loaded_can_be_turned_off() -> None:
    model = FakeModel()
    gateway = AiGateway(model, "m", _limits(keep_warm_interval=0))

    gateway.start()
    await _until(lambda: gateway.status is AiStatus.READY)
    await asyncio.sleep(0.05)

    assert len(model.calls) == 1
    await gateway.shutdown()


async def test_the_embedding_model_is_loaded_and_kept_loaded_too() -> None:
    """A question is embedded before the material is searched, so an
    embedder the server has unloaded delays the first reply just as an
    unloaded chat model would."""
    model = FakeModel()
    gateway = AiGateway(model, "chat", _limits(keep_warm_interval=0.02), embedding_model="embedder")

    gateway.start()
    await _until(lambda: len(model.calls) >= 6)
    await gateway.shutdown()

    assert model.calls[:2] == [("chat", "Reply with OK."), ("embedder", "ok")]
    asked = [name for name, _ in model.calls]
    assert asked.count("chat") >= 2 and asked.count("embedder") >= 2


async def test_only_the_idle_model_is_asked_to_stay() -> None:
    """A class is chatting, so the chat model needs no reminder. Nobody has
    searched for a while, so the embedder does."""
    model = FakeModel()
    gateway = AiGateway(model, "chat", _limits(keep_warm_interval=0.15), embedding_model="embedder")
    gateway.start()
    await _until(lambda: len(model.calls) == 2)

    async with asyncio.timeout(WAIT_SECONDS):
        while [name for name, _ in model.calls].count("embedder") < 3:
            await gateway.complete(_ask("a student's question"))
            await asyncio.sleep(0.02)
    await gateway.shutdown()

    assert ("chat", "Reply with OK.") not in model.calls[2:]


async def test_a_model_that_is_down_is_asked_to_stay_once_an_interval() -> None:
    """Loaded, then gone. The reminders must not turn into a tight loop
    against a server that is not answering."""
    model = FakeModel()
    gateway = AiGateway(model, "m", _limits(keep_warm_interval=0.05, breaker_failures=1000))
    gateway.start()
    await _until(lambda: gateway.status is AiStatus.READY)

    model.steps.extend([ModelUnreachableError("gone")] * 1000)
    await asyncio.sleep(0.3)
    await gateway.shutdown()

    # About six intervals passed. A tight loop would have made hundreds, and
    # a reminder that gave up after its first failure only two.
    assert 4 <= len(model.calls) <= 12


async def test_a_model_that_is_not_installed_is_not_warmed_up_five_times() -> None:
    missing = ModelUnreachableError("the model is not installed", retry=False)
    model = FakeModel(missing)
    gateway = AiGateway(model, "m", QUICK)

    await gateway.warm_up()

    assert len(model.calls) == 1
    assert gateway.status is AiStatus.COLD


async def test_shutdown_stops_work_in_flight_and_refuses_more() -> None:
    model = FakeModel(HANG, ["Think ", HANG])
    gateway = AiGateway(model, "m", QUICK)
    gateway.start()
    await _until(lambda: model.active == 1)

    async with gateway.stream(_ask()) as reply:
        assert await anext(reply) == "Think "
        await gateway.shutdown()
        assert [text async for text in reply] == []

    assert model.active == 0
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())
    # The same process can start again, as a test client's lifespan does.
    gateway.start(warm_up=False)
    assert (await gateway.complete(_ask())).text == "ok"


# -- the OpenAI-compatible client ----------------------------------------------------------

_REQUEST = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


def _status_error(kind: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    return kind("refused", response=httpx.Response(status, request=_REQUEST), body=None)


@pytest.mark.parametrize(
    ("raised", "expected", "retry"),
    [
        (openai.APIConnectionError(request=_REQUEST), ModelUnreachableError, True),
        (openai.APITimeoutError(request=_REQUEST), ModelUnreachableError, True),
        (_status_error(openai.InternalServerError, 500), ModelUnreachableError, True),
        (_status_error(openai.RateLimitError, 429), ModelUnreachableError, True),
        (_status_error(openai.APIStatusError, 408), ModelUnreachableError, True),
        (_status_error(openai.ConflictError, 409), ModelUnreachableError, True),
        (_status_error(openai.NotFoundError, 404), ModelUnreachableError, False),
        (_status_error(openai.BadRequestError, 400), ModelRejectedError, None),
    ],
)
async def test_the_clients_errors_say_whether_trying_again_can_help(
    raised: openai.OpenAIError, expected: type[Exception], retry: bool | None
) -> None:
    client = OpenAIModelClient(_OpenAIStandIn(raised))

    with pytest.raises(expected) as caught:
        await client.complete("m", [{"role": "user", "content": "q"}], max_tokens=None)

    if retry is not None:
        assert caught.value.retry is retry


async def test_the_client_closes_a_stream_its_reader_abandons() -> None:
    response = _StreamedResponse(["Think ", "about ", "light."])
    client = OpenAIModelClient(_OpenAIStandIn(response))

    pieces = client.stream("m", [{"role": "user", "content": "q"}], max_tokens=64)
    assert await anext(pieces) == "Think "
    await pieces.aclose()

    assert response.closed is True


async def test_the_client_orders_vectors_by_the_index_they_carry() -> None:
    from types import SimpleNamespace

    data = [SimpleNamespace(index=1, embedding=[0.2]), SimpleNamespace(index=0, embedding=[0.1])]
    client = OpenAIModelClient(_OpenAIStandIn(SimpleNamespace(data=data)))

    assert await client.embed("embedder", ["first", "second"]) == [[0.1], [0.2]]


class _StreamedResponse:
    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[object]:
        for piece in self._pieces:
            yield _chunk(piece)

    async def close(self) -> None:
        self.closed = True


def _chunk(text: str) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class _OpenAIStandIn:
    """The one method of AsyncOpenAI the client calls."""

    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.chat = self
        self.completions = self
        self.embeddings = self

    async def create(self, **_: object) -> object:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


# -- wiring ------------------------------------------------------------------------


def test_startup_warms_the_model_only_when_configured_to(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup opens the gateway and shutdown closes it, and the warm-up
    follows AI_WARMUP_ENABLED, which the suite turns off."""
    from fastapi.testclient import TestClient

    from app import main as main_module

    model = FakeModel()
    gateway = AiGateway(model, "m", QUICK)
    monkeypatch.setattr(main_module, "get_ai_gateway", lambda: gateway)
    settings = main_module.get_settings()

    with TestClient(app):
        assert gateway.status is AiStatus.COLD
    assert model.calls == []

    monkeypatch.setattr(settings, "ai_warmup_enabled", True)
    with TestClient(app) as client:
        client.portal.call(_until, lambda: gateway.status is AiStatus.READY)
    assert model.calls == [("m", "Reply with OK.")]
    with pytest.raises(AiUnavailableError):
        asyncio.run(gateway.complete(_ask()))


def test_the_limits_come_from_settings() -> None:
    settings = Settings(
        ai_max_concurrency=4, ai_queue_limit=10, ai_max_attempts=2, ai_breaker_failures=7
    )

    limits = AiLimits.from_settings(settings)

    assert (
        limits.max_concurrency,
        limits.queue_limit,
        limits.max_attempts,
        limits.breaker_failures,
    ) == (4, 10, 2, 7)
    assert limits.request_timeout == settings.ai_request_timeout_seconds


async def test_material_processing_takes_its_turn_through_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upload's embeddings and questions must not reach the model around
    the queue, and wait behind everyone a person is watching for."""
    model = FakeModel("[]")
    gateway = AiGateway(model, "qwen2.5", QUICK, embedding_model="embedder")
    priorities: list[Priority] = []
    acquire = gateway._slots.acquire

    async def spy(priority: Priority, patience: float) -> None:
        priorities.append(priority)
        assert patience == uploads_module.MATERIAL_QUEUE_TIMEOUT_SECONDS
        await acquire(priority, patience)

    monkeypatch.setattr(gateway._slots, "acquire", spy)
    monkeypatch.setattr(uploads_module, "get_ai_gateway", lambda: gateway)
    uploads_module.get_material_pipeline.cache_clear()
    try:
        pipeline = uploads_module.get_material_pipeline()
        response = await pipeline.generator._client.chat.completions.create(
            model=pipeline.generator.model,
            messages=[{"role": "user", "content": "Write questions."}],
        )
        vectors = await pipeline.embedder._client.embed(["a chunk"])
    finally:
        uploads_module.get_material_pipeline.cache_clear()

    assert response.choices[0].message.content == "[]"
    assert vectors == [[7.0]]
    assert model.calls == [(pipeline.generator.model, "Write questions."), ("embedder", "a chunk")]
    assert priorities == [Priority.BACKGROUND, Priority.BACKGROUND]


async def test_readiness_reports_what_the_gateway_makes_of_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import health

    clock = Clock()
    limits = _limits(max_attempts=1, breaker_failures=1)
    gateway = AiGateway(FakeModel(ModelUnreachableError("down")), "m", limits, clock=clock)
    monkeypatch.setattr(health, "get_ai_gateway", lambda: gateway)

    assert health._gateway_detail() == "gateway cold"
    with pytest.raises(AiUnavailableError):
        await gateway.complete(_ask())
    assert health._gateway_detail() == "gateway unavailable"
    clock.now = 31.0
    await gateway.complete(_ask())
    assert health._gateway_detail() == "gateway ready"
