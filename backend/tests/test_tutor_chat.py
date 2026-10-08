"""The tutor's chat route.

Owner: General CS, Phase 5.

Cyber 1's guard decides what a student may be told, and has its own tests.
These cover what the route owes around it: who may ask, how often, which
material is searched, that the model is reached through the gateway and
stopped when the student stops reading, and that the reply arrives as the
events the student panel parses.

No test here talks to a model. FakeTutorModel plays one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.auth.store import LECTURER_ID, STUDENT_ID, get_consent_repository
from app.core.config import get_settings
from app.core.errors import ConflictError, RateLimitedError
from app.models.course import Course
from app.models.material import Material
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.session import Session as SessionModel
from app.schemas.identity import ConsentType, Role
from app.services import tutor_chat
from app.services.ai_gateway import (
    AiGateway,
    AiLimits,
    AiRequest,
    Message,
    ModelUnreachableError,
    Priority,
)
from app.services.tutor_chat import ChatContext, ChatLimiter, MaterialSource, TutorExchange
from app.services.tutor_guardrails import ERROR_DETAIL, MAX_QUESTION_CHARS

from .session_support import (
    add_course,
    add_lecturer,
    add_question,
    create_session,
    enrol,
    sign_in_as,
)

WAIT_SECONDS = 5.0
QUESTION = "Why are the base layers frozen?"
EXCERPT = "Transfer learning reuses a trained network."
# A reply the guard lets through: a question back, citing the first excerpt.
REPLY = ("Which layers ", "are general? [1]")
HANG = object()

LIMITS = AiLimits(
    max_concurrency=2,
    queue_timeout=WAIT_SECONDS,
    request_timeout=WAIT_SECONDS,
    first_token_timeout=WAIT_SECONDS,
    stream_idle_timeout=WAIT_SECONDS,
    stream_timeout=WAIT_SECONDS,
    max_attempts=1,
    retry_pause=0.0,
    breaker_failures=1000,
)


def _vector(axis: int = 0) -> list[float]:
    """A unit vector. Two on the same axis are identical, two on different
    axes as far apart as cosine distance goes."""
    vector = [0.0] * get_settings().embedding_dim
    vector[axis] = 1.0
    return vector


class FakeTutorModel:
    """Embeds every text onto one axis, and streams the reply it is given."""

    def __init__(self) -> None:
        self.reply: Sequence[object] = REPLY
        self.embed_error: Exception | None = None
        self.embedded: list[tuple[str, list[str]]] = []
        self.prompts: list[tuple[str, Sequence[Message]]] = []
        self.streaming = 0
        self.closed_streams = 0

    async def complete(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> str:
        raise AssertionError("the tutor streams its replies")

    async def stream(
        self, model: str, messages: Sequence[Message], *, max_tokens: int | None
    ) -> AsyncIterator[str]:
        self.prompts.append((model, messages))
        self.streaming += 1
        try:
            for piece in self.reply:
                if piece is HANG:
                    await asyncio.Event().wait()
                if isinstance(piece, Exception):
                    raise piece
                yield str(piece)
        finally:
            self.streaming -= 1
            self.closed_streams += 1

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        self.embedded.append((model, list(texts)))
        if self.embed_error is not None:
            raise self.embed_error
        return [_vector() for _ in texts]


@pytest.fixture
async def tutor(db, monkeypatch: pytest.MonkeyPatch):
    """The route's gateway and limiter, replaced with ones a test can see into."""
    _, factory, created = db
    model = FakeTutorModel()
    gateway = AiGateway(model, "chat-model", LIMITS, embedding_model=get_settings().embedding_model)
    limiter = ChatLimiter(per_minute=3, longest_exchange=60.0)
    requests: list[AiRequest] = []
    stream = gateway.stream

    def spying_stream(request: AiRequest):  # noqa: ANN202
        requests.append(request)
        return stream(request)

    monkeypatch.setattr(gateway, "stream", spying_stream)
    monkeypatch.setattr(tutor_chat, "get_ai_gateway", lambda: gateway)
    monkeypatch.setattr(tutor_chat, "get_chat_limiter", lambda: limiter)
    yield SimpleNamespace(model=model, gateway=gateway, limiter=limiter, requests=requests)
    # Before the db fixture removes the materials these excerpts belong to.
    async with factory() as cleanup:
        await cleanup.execute(
            delete(RagChunk).where(RagChunk.source_material_id.in_(created["material"]))
        )
        await cleanup.commit()


async def _excerpt(
    db,
    material_id: UUID,
    text: str = EXCERPT,
    *,
    axis: int = 0,
    page: int | None = 3,
    model: str | None = None,
) -> UUID:
    _, factory, _ = db
    async with factory() as seed:
        chunk = RagChunk(
            source_material_id=material_id,
            chunk_index=0,
            source_page=page,
            chunk_text=text,
            embedding_vector=_vector(axis),
            embedding_model=model or get_settings().embedding_model,
        )
        seed.add(chunk)
        await seed.commit()
    return chunk.chunk_id


async def _running_class(db, app) -> SimpleNamespace:
    """A session in progress with the development student enrolled and signed
    in, and one excerpt of its lecturer's material to answer from."""
    client, factory, created = db
    course = await add_course(factory, created)
    question_id = await add_question(db, course, LECTURER_ID)
    material_id = created["material"][-1]
    chunk_id = await _excerpt(db, material_id)
    await enrol(factory, course)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    session = create_session(client, course)
    assert client.post(f"/api/v1/sessions/{session['id']}/start").status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    return SimpleNamespace(
        id=session["id"],
        course=course,
        question_id=question_id,
        material_id=material_id,
        chunk_id=chunk_id,
    )


def _ask(client, session_id: str, question: str = QUESTION, request_id: str = "req-1"):  # noqa: ANN001, ANN202
    return client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"request_id": request_id, "question": question},
    )


def _events(response) -> list[dict[str, Any]]:  # noqa: ANN001
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


def _types(events: list[dict[str, Any]]) -> list[str]:
    return [event["type"] for event in events]


# -- the reply ---------------------------------------------------------------------


async def test_a_student_is_answered_from_the_sessions_material(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)

    response = _ask(client, live.id)

    events = _events(response)
    assert response.headers["content-type"].startswith("application/x-ndjson")
    types = _types(events)
    assert (types[0], types[-1]) == ("accepted", "completed")
    # The guard may release the text in more pieces than the model wrote it
    # in, and adds follow-up prompts of its own.
    assert set(types) <= {"accepted", "delta", "citation", "follow_up", "completed"}
    assert {event["request_id"] for event in events} == {"req-1"}
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "".join(REPLY)
    assert [e["citation"] for e in events if e["type"] == "citation"] == [
        {
            "id": str(live.chunk_id),
            "material_title": "week1.pdf",
            "source_page": 3,
            "source_slide": None,
            "excerpt": EXCERPT,
        }
    ]


async def test_slides_are_cited_by_slide(db, app, tutor) -> None:
    client, factory, _ = db
    live = await _running_class(db, app)
    async with factory() as rename:
        material = await rename.get(Material, live.material_id)
        material.filename = "Week 1.PPTX"
        await rename.commit()

    citation = next(e for e in _events(_ask(client, live.id)) if e["type"] == "citation")

    assert (citation["citation"]["source_page"], citation["citation"]["source_slide"]) == (None, 3)
    assert citation["citation"]["material_title"] == "Week 1.PPTX"


async def test_the_question_and_the_reply_go_through_the_gateway_as_live_work(
    db, app, tutor
) -> None:
    """A student is waiting, so both calls are served ahead of an upload."""
    client, _, _ = db
    live = await _running_class(db, app)
    priorities: list[Priority] = []
    acquire = tutor.gateway._slots.acquire

    async def spy(priority: Priority, patience: float) -> None:
        priorities.append(priority)
        await acquire(priority, patience)

    tutor.gateway._slots.acquire = spy

    _events(_ask(client, live.id))

    assert priorities == [Priority.LIVE, Priority.LIVE]
    assert tutor.model.embedded == [(get_settings().embedding_model, [QUESTION])]
    assert [request.purpose for request in tutor.requests] == ["tutor"]
    model, messages = tutor.model.prompts[0]
    assert model == "chat-model"
    assert [message["role"] for message in messages] == ["system", "user"]
    assert EXCERPT in messages[0]["content"] + messages[1]["content"]


async def test_a_class_with_no_material_is_told_there_is_nothing_to_draw_on(db, app, tutor) -> None:
    client, factory, _ = db
    live = await _running_class(db, app)
    async with factory() as remove:
        await remove.execute(delete(RagChunk).where(RagChunk.chunk_id == live.chunk_id))
        await remove.commit()

    assert _types(_events(_ask(client, live.id))) == ["accepted", "empty_retrieval"]
    assert tutor.model.prompts == []


async def test_only_this_lecturers_finished_material_is_searched(db, app, tutor) -> None:
    """Another lecturer's upload for the same course, and a material still
    being processed, are both nearer the question than nothing. Neither may
    be quoted to this class."""
    client, factory, created = db
    live = await _running_class(db, app)
    other = await add_lecturer(factory, created)
    async with factory() as seed:
        theirs = Material(
            course_id=live.course.id,
            filename="theirs.pdf",
            content_type="application/pdf",
            size_bytes=10,
            status="completed",
            uploaded_by_user_id=other,
        )
        unfinished = Material(
            course_id=live.course.id,
            filename="unfinished.pdf",
            content_type="application/pdf",
            size_bytes=10,
            status="processing",
            uploaded_by_user_id=LECTURER_ID,
        )
        seed.add_all([theirs, unfinished])
        await seed.commit()
    created["material"] += [theirs.id, unfinished.id]
    await _excerpt(db, theirs.id, "Another lecturer's notes on freezing layers.")
    await _excerpt(db, unfinished.id, "A half-processed draft about freezing layers.")

    _events(_ask(client, live.id))

    prompt = " ".join(message["content"] for message in tutor.model.prompts[0][1])
    assert EXCERPT in prompt
    assert "Another lecturer" not in prompt and "half-processed" not in prompt


async def test_excerpts_embedded_by_another_model_are_left_out(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    await _excerpt(db, live.material_id, "Embedded by a model since replaced.", model="old-model")

    _events(_ask(client, live.id))

    prompt = " ".join(message["content"] for message in tutor.model.prompts[0][1])
    assert EXCERPT in prompt and "since replaced" not in prompt


async def test_only_the_nearest_excerpts_are_put_to_the_model(
    db, app, tutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    for number in range(4):
        await _excerpt(db, live.material_id, f"Further point number {number}.")
    monkeypatch.setattr(get_settings(), "chat_retrieved_chunks", 2)

    _events(_ask(client, live.id))

    prompt = " ".join(message["content"] for message in tutor.model.prompts[0][1])
    quoted = prompt.count(EXCERPT) + prompt.count("Further point number")
    assert quoted == 2


async def test_the_nearest_excerpt_is_the_one_chosen(
    db, app, tutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With room for one excerpt, it must be the one closest to the question
    and not whichever the database happens to return first."""
    client, factory, _ = db
    live = await _running_class(db, app)
    async with factory() as remove:
        await remove.execute(delete(RagChunk).where(RagChunk.chunk_id == live.chunk_id))
        await remove.commit()
    for number in range(3):
        await _excerpt(db, live.material_id, f"An unrelated passage {number}.", axis=number + 1)
    await _excerpt(db, live.material_id, "The passage about frozen layers.")
    monkeypatch.setattr(get_settings(), "chat_retrieved_chunks", 1)

    _events(_ask(client, live.id))

    prompt = " ".join(message["content"] for message in tutor.model.prompts[0][1])
    assert "The passage about frozen layers." in prompt
    assert "unrelated passage" not in prompt


async def test_the_tutor_is_told_which_question_is_open_and_its_answer(
    db, app, tutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard keeps the open question's answer from the student, and can
    only do that if it is given the answer. The copy students are sent does
    not carry it, so it comes from the stored question."""
    client, _, _ = db
    live = await _running_class(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    delivered = client.post(f"/api/v1/sessions/{live.id}/questions/{live.question_id}:deliver")
    assert delivered.status_code == 202, delivered.text
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    seen: list[object] = []
    guarded_chat = tutor_chat.guarded_chat

    def spy(**arguments: Any):  # noqa: ANN202
        seen.append(arguments["open_question"])
        return guarded_chat(**arguments)

    monkeypatch.setattr(tutor_chat, "guarded_chat", spy)

    _events(_ask(client, live.id))

    assert (seen[0].prompt, seen[0].options, seen[0].correct_option) == (
        "Which planet is largest?",
        ("Mars", "Jupiter", "Venus"),
        1,
    )


async def test_with_no_question_open_the_tutor_is_told_so(
    db, app, tutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    seen: list[object] = []
    guarded_chat = tutor_chat.guarded_chat

    def spy(**arguments: Any):  # noqa: ANN202
        seen.append(arguments["open_question"])
        return guarded_chat(**arguments)

    monkeypatch.setattr(tutor_chat, "guarded_chat", spy)

    _events(_ask(client, live.id))

    assert seen == [None]


# -- when the model cannot answer ---------------------------------------------------------


async def test_a_model_that_cannot_answer_is_a_fixed_error_on_the_stream(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    tutor.model.reply = (ModelUnreachableError("connection refused at 10.0.0.5"),)

    events = _events(_ask(client, live.id))

    assert _types(events) == ["accepted", "error"]
    assert events[-1]["detail"] == ERROR_DETAIL
    # And the student may ask again at once.
    tutor.model.reply = REPLY
    assert _types(_events(_ask(client, live.id, request_id="req-2")))[-1] == "completed"


async def test_a_question_that_cannot_be_embedded_is_a_fixed_error(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    tutor.model.embed_error = ModelUnreachableError("down")

    events = _events(_ask(client, live.id))

    assert _types(events) == ["accepted", "error"]
    assert tutor.model.prompts == []


# -- who may ask ------------------------------------------------------------------------


async def test_a_student_not_enrolled_for_the_session_is_told_it_is_not_there(
    db, app, tutor
) -> None:
    client, factory, created = db
    live = await _running_class(db, app)
    await enrol(factory, await add_course(factory, created))

    refused = _ask(client, live.id)
    missing = _ask(client, str(uuid4()))

    assert (refused.status_code, missing.status_code) == (404, 404)
    assert refused.json()["error"]["message"] == missing.json()["error"]["message"]
    assert tutor.model.embedded == []


async def test_a_session_that_is_over_has_no_tutor(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.post(f"/api/v1/sessions/{live.id}/end").status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    assert _ask(client, live.id).status_code == 404


async def test_staff_are_not_the_tutors_students(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)

    assert _ask(client, live.id).status_code == 403


async def test_a_student_who_has_not_agreed_to_the_terms_is_refused(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    get_consent_repository(get_settings()).record(STUDENT_ID, ConsentType.TERMS, False)

    refused = _ask(client, live.id)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert tutor.model.embedded == []


@pytest.mark.parametrize(
    "body",
    [
        {"request_id": "req-1", "question": "x" * (MAX_QUESTION_CHARS + 1)},
        {"request_id": "req-1", "question": ""},
        {"request_id": "req\n1", "question": QUESTION},
        {"request_id": "r" * 65, "question": QUESTION},
        {"question": QUESTION},
    ],
)
async def test_a_request_out_of_bounds_is_refused_before_anything_runs(
    db, app, tutor, body: dict[str, str]
) -> None:
    client, _, _ = db
    live = await _running_class(db, app)

    refused = client.post(f"/api/v1/sessions/{live.id}/chat", json=body)

    assert refused.status_code == 422
    assert tutor.model.embedded == []


# -- how often ---------------------------------------------------------------------------


async def test_a_student_may_ask_only_so_often(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    for number in range(3):
        assert _ask(client, live.id, request_id=f"req-{number}").status_code == 200

    refused = _ask(client, live.id, request_id="one-too-many")

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= refused.json()["error"]["detail"]["retry_after_seconds"] <= 60
    assert len(tutor.model.prompts) == 3


async def test_a_refused_request_does_not_count_against_the_student(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    for _ in range(5):
        assert _ask(client, str(uuid4())).status_code == 404

    assert _ask(client, live.id).status_code == 200


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_limit_is_each_students_own_and_lifts_after_a_minute() -> None:
    clock = Clock()
    limiter = ChatLimiter(per_minute=2, longest_exchange=300.0, clock=clock)
    asker, classmate = uuid4(), uuid4()
    for _ in range(2):
        limiter.admit(asker)
        limiter.finish(asker)

    with pytest.raises(RateLimitedError) as refused:
        limiter.admit(asker)
    limiter.admit(classmate)

    assert refused.value.detail == {"retry_after_seconds": 60}
    clock.now = 60.0
    limiter.admit(asker)


def test_a_student_has_one_exchange_at_a_time() -> None:
    clock = Clock()
    limiter = ChatLimiter(per_minute=10, longest_exchange=300.0, clock=clock)
    asker = uuid4()
    limiter.admit(asker)

    with pytest.raises(ConflictError):
        limiter.admit(asker)

    limiter.finish(asker)
    limiter.admit(asker)


def test_an_exchange_that_never_reports_back_does_not_lock_the_student_out() -> None:
    """A response the client abandons before it starts never runs the code
    that marks the exchange finished."""
    clock = Clock()
    limiter = ChatLimiter(per_minute=10, longest_exchange=300.0, clock=clock)
    asker = uuid4()
    limiter.admit(asker)

    clock.now = 299.0
    with pytest.raises(ConflictError):
        limiter.admit(asker)
    clock.now = 300.0
    limiter.admit(asker)


def test_students_who_stop_asking_are_forgotten() -> None:
    clock = Clock()
    limiter = ChatLimiter(per_minute=10, longest_exchange=300.0, clock=clock)
    for _ in range(50):
        student = uuid4()
        limiter.admit(student)
        clock.now += 61.0
        limiter.finish(student)

    assert limiter._asked == {} and limiter._running == {}


def test_the_longest_exchange_follows_the_gateways_limits() -> None:
    settings = get_settings()

    assert tutor_chat.longest_exchange(settings) == (
        2 * settings.ai_queue_timeout_seconds
        + settings.ai_request_timeout_seconds * settings.ai_max_attempts
        + settings.ai_stream_timeout_seconds
    )


# -- a student who stops reading ------------------------------------------------------------


async def test_a_student_who_leaves_stops_the_model_and_may_ask_again(db, tutor) -> None:
    """The panel aborts its request, and the server stops reading the reply.
    The model must be stopped with it, and the student not left counted as
    still mid-exchange."""
    _, factory, created = db
    course = await add_course(factory, created)
    await add_question(db, course, LECTURER_ID)
    material_id = created["material"][-1]
    await _excerpt(db, material_id)
    tutor.model.reply = ("Which layers ", HANG)
    context = ChatContext(
        session_id=uuid4(),
        user_id=STUDENT_ID,
        open_question=None,
        materials={material_id: MaterialSource(title="week1.pdf", slides=False)},
    )
    tutor.limiter.admit(STUDENT_ID)
    exchange = TutorExchange(
        context, gateway=tutor.gateway, limiter=tutor.limiter, sessions=lambda: factory
    )

    lines = exchange.lines("req-1", QUESTION)
    assert json.loads(await anext(lines))["type"] == "accepted"
    reading = asyncio.create_task(anext(lines))
    async with asyncio.timeout(WAIT_SECONDS):
        while tutor.model.streaming == 0:  # noqa: ASYNC110 - state, not an event
            await asyncio.sleep(0)
    reading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reading
    await lines.aclose()

    assert (tutor.model.streaming, tutor.model.closed_streams) == (0, 1)
    tutor.limiter.admit(STUDENT_ID)


async def test_a_reader_who_stops_between_pieces_stops_the_model_at_once(db, tutor) -> None:
    """The reader has part of the reply and asks for no more, while the model
    is still writing. Nothing is waiting on the model at that moment, so only
    closing the guard's stream on the way out reaches it."""
    _, factory, created = db
    course = await add_course(factory, created)
    await add_question(db, course, LECTURER_ID)
    material_id = created["material"][-1]
    await _excerpt(db, material_id)
    tutor.model.reply = ("Which layers are general? [1] ", "Why might that matter? ", HANG)
    context = ChatContext(
        session_id=uuid4(),
        user_id=STUDENT_ID,
        open_question=None,
        materials={material_id: MaterialSource(title="week1.pdf", slides=False)},
    )
    tutor.limiter.admit(STUDENT_ID)
    exchange = TutorExchange(
        context, gateway=tutor.gateway, limiter=tutor.limiter, sessions=lambda: factory
    )

    lines = exchange.lines("req-1", QUESTION)
    async with asyncio.timeout(WAIT_SECONDS):
        while json.loads(await anext(lines))["type"] != "delta":
            pass
    assert tutor.model.streaming == 1
    await lines.aclose()

    assert (tutor.model.streaming, tutor.model.closed_streams) == (0, 1)
    tutor.limiter.admit(STUDENT_ID)


async def test_nothing_about_the_question_is_logged(db, app, tutor, caplog) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    secret = "Why does my seizure medication make transfer learning hard to follow?"

    with caplog.at_level("DEBUG"):
        _events(_ask(client, live.id, question=secret))

    assert "seizure" not in caplog.text
    assert f"session={live.id}" in caplog.text and "outcome=" in caplog.text


async def test_the_session_and_course_are_left_as_they_were(db, app, tutor) -> None:
    """Asking the tutor reads. It must not change the class it is asked in."""
    client, factory, _ = db
    live = await _running_class(db, app)

    _events(_ask(client, live.id))

    async with factory() as check:
        status = await check.scalar(
            select(SessionModel.status).where(SessionModel.session_id == UUID(live.id))
        )
        question = await check.get(Question, live.question_id)
        course = await check.get(Course, live.course.id)
    assert (status, question.status, course.code) == ("active", "staged", live.course.code)
