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
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select

from app.auth.store import LECTURER_ID, STUDENT_ID, get_consent_repository
from app.core.config import get_settings
from app.core.errors import ConflictError, RateLimitedError
from app.models.comprehension_result import ComprehensionResult
from app.models.course import Course
from app.models.course_enrollment import CourseEnrollment
from app.models.material import Material
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.session import Session as SessionModel
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
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
        # Set once a reply reaches HANG: the model is mid-answer and waiting.
        self.hanging = asyncio.Event()
        # Database connections in use each time the model was asked to write.
        self.connections_held: list[int] = []
        self.connections_in_use = lambda: 0

    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        max_tokens: int | None,
        options: object = None,
    ) -> str:
        raise AssertionError("the tutor streams its replies")

    async def stream(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        max_tokens: int | None,
        options: object = None,
    ) -> AsyncIterator[str]:
        self.prompts.append((model, messages))
        self.connections_held.append(self.connections_in_use())
        self.streaming += 1
        try:
            for piece in self.reply:
                if piece is HANG:
                    self.hanging.set()
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
    pool = factory.kw["bind"].sync_engine.pool
    in_use = 0

    def taken(*_: object) -> None:
        nonlocal in_use
        in_use += 1

    def returned(*_: object) -> None:
        nonlocal in_use
        in_use -= 1

    event.listen(pool, "checkout", taken)
    event.listen(pool, "checkin", returned)
    model.connections_in_use = lambda: in_use
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
    event.remove(pool, "checkout", taken)
    event.remove(pool, "checkin", returned)
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
            "number": 1,
            "material_title": "week1.pdf",
            "source_page": 3,
            "source_slide": None,
            "source_section": None,
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


async def test_no_database_connection_is_held_while_the_model_writes(db, app, tutor) -> None:
    """The request's session lasts as long as the response, which here is as
    long as the reply. A class asking at once would otherwise hold a
    connection each and leave none for the search or the live session."""
    client, _, _ = db
    live = await _running_class(db, app)

    assert _types(_events(_ask(client, live.id)))[-1] == "completed"

    assert tutor.model.connections_held == [0]


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


async def test_ended_session_retains_material_tutor_for_current_members(db, app, tutor) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.post(f"/api/v1/sessions/{live.id}/end").status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    result = _ask(client, live.id)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert '"type":"completed"' in result.text.replace(" ", "")
    # Ending a session does not bypass current course membership.
    await enrol(db[1], await add_course(db[1], db[2]))
    assert _ask(client, live.id).status_code == 404


async def test_revision_tutor_uses_only_your_marked_answers_across_completed_lessons_in_the_subject(
    db, app, tutor
) -> None:
    client, factory, created = db
    live = await _running_class(db, app)
    partial_id = await add_question(db, live.course, LECTURER_ID, question_type="free_text")
    uncertain_id = await add_question(db, live.course, LECTURER_ID)
    other_id = await add_question(db, live.course, LECTURER_ID)
    unrelated_course = await add_course(factory, created)
    excluded_id = await add_question(db, unrelated_course, LECTURER_ID)
    other_user = uuid4()
    async with factory() as seed:
        seed.add(
            User(user_id=other_user, name="Other", role="student", email=f"{other_user}@t.test")
        )
        await seed.commit()
    created["user"].append(other_user)
    await enrol(factory, live.course, other_user)
    async with factory() as seed:
        students = dict(
            (
                await seed.execute(
                    select(Student.user_id, Student.student_id).where(
                        Student.user_id.in_((STUDENT_ID, other_user))
                    )
                )
            ).all()
        )
        entry = await seed.get(SessionModel, UUID(live.id))
        assert entry is not None
        entry.title = "Week 10"
        lesson_date = datetime.now(UTC) - timedelta(days=63)
        earlier = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=live.course.id,
            title="Week 1",
            start_time=lesson_date,
            ended_at=lesson_date + timedelta(hours=1),
            mode=entry.mode,
            status="ended",
        )
        unrelated = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=unrelated_course.id,
            title="Another subject",
            start_time=lesson_date,
            ended_at=lesson_date + timedelta(hours=1),
            mode=entry.mode,
            status="ended",
        )
        in_progress = SessionModel(
            instructor_id=LECTURER_ID,
            course_id=live.course.id,
            title="Unfinished lesson",
            start_time=lesson_date,
            mode=entry.mode,
            status="active",
        )
        seed.add_all((earlier, unrelated, in_progress))
        await seed.flush()
        for question_id, topic in (
            (live.question_id, "Planet size"),
            (partial_id, "Orbital motion"),
            (uncertain_id, "Uncertain topic"),
            (other_id, "Private topic"),
        ):
            question = await seed.get(Question, question_id)
            assert question is not None
            question.topic = topic
        session_id = UUID(live.id)
        uncertain = StudentResponse(
            session_id=session_id,
            student_id=students[STUDENT_ID],
            question_id=uncertain_id,
            free_text="An unverified answer",
        )
        partial = StudentResponse(
            session_id=earlier.session_id,
            student_id=students[STUDENT_ID],
            question_id=partial_id,
            free_text="A partial answer",
        )
        seed.add_all(
            [
                uncertain,
                partial,
                StudentResponse(
                    session_id=unrelated.session_id,
                    student_id=students[STUDENT_ID],
                    question_id=excluded_id,
                    selected_option=0,
                    is_correct=False,
                ),
                StudentResponse(
                    session_id=in_progress.session_id,
                    student_id=students[STUDENT_ID],
                    question_id=partial_id,
                    selected_option=0,
                    is_correct=False,
                ),
                StudentResponse(
                    session_id=session_id,
                    student_id=students[STUDENT_ID],
                    question_id=live.question_id,
                    selected_option=0,
                    is_correct=False,
                ),
                StudentResponse(
                    session_id=session_id,
                    student_id=students[other_user],
                    question_id=other_id,
                    selected_option=0,
                    is_correct=False,
                ),
            ]
        )
        await seed.flush()
        seed.add(
            ComprehensionResult(
                response_id=uncertain.response_id,
                label="struggling",
                confidence_score=0.3,
                score=0.2,
                ai_feedback_text="Uncertain",
            )
        )
        seed.add(
            ComprehensionResult(
                response_id=partial.response_id,
                label="partial",
                confidence_score=0.8,
                score=0.5,
                ai_feedback_text="Partial",
            )
        )
        await seed.commit()

    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.post(f"/api/v1/sessions/{live.id}/end").status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)
    choices = _events(_ask(client, live.id, "What should I revise?"))
    assert _types(choices) == ["accepted", "delta", "follow_up", "completed"]
    assert choices[1]["text"] == "Which subject would you like to revise?"
    option = choices[2]["prompt"]
    assert option == f"Revise {live.course.code} — {live.course.name}"
    response = client.post(
        f"/api/v1/sessions/{live.id}/chat",
        json={
            "request_id": "req-1",
            "question": live.course.code,
            "history": [{"question": "What should I revise?", "answer": choices[1]["text"]}],
        },
    )
    events = _events(response)
    assert response.headers["cache-control"] == "no-store"
    assert _types(events) == ["accepted", "delta", "delta", "delta", "citation", "completed"]
    assert live.course.code in events[1]["text"]
    assert "Week 1 (" in events[2]["text"]
    assert "Revisit Orbital motion" in events[2]["text"]
    assert "partially understood" in events[2]["text"]
    assert "A lesson excerpt isn’t available" in events[2]["text"]
    assert "Week 10 (" in events[3]["text"]
    assert "Revisit Planet size" in events[3]["text"]
    assert "Which planet is largest?" in events[3]["text"]
    assert "lesson excerpt [2]" in events[3]["text"]
    assert events[4]["citation"]["source_page"] == 3
    assert events[4]["citation"]["material_title"] == "week1.pdf"
    assert events[4]["citation"]["source_session_id"] == live.id
    assert "Another subject" not in response.text
    assert "Unfinished lesson" not in response.text
    assert "A partial answer" not in response.text
    assert "Jupiter" not in response.text
    assert "Uncertain topic" not in response.text
    assert "Private topic" not in response.text
    assert tutor.model.prompts == tutor.model.embedded == []

    from_earlier = _ask(client, str(earlier.session_id), option)
    assert _events(from_earlier) == events

    await enrol(factory, await add_course(factory, created))
    assert _ask(client, live.id, "What should I revise?").status_code == 404


async def test_revision_tutor_selects_another_enrolled_subject_and_rejects_unknown_subjects(
    db, app, tutor
) -> None:
    client, factory, created = db
    live = await _running_class(db, app)
    other = await add_course(factory, created)
    async with factory() as seed:
        student_id = await seed.scalar(
            select(Student.student_id).where(Student.user_id == STUDENT_ID)
        )
        seed.add(CourseEnrollment(student_id=student_id, course_id=other.id))
        await seed.commit()
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    assert client.post(f"/api/v1/sessions/{live.id}/end").status_code == 200
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    choices = _events(_ask(client, live.id, "  What should I REVIEW?  "))
    options = {e["prompt"] for e in choices if e["type"] == "follow_up"}
    option = f"Revise {other.code} — {other.name}"
    assert options == {option, f"Revise {live.course.code} — {live.course.name}"}
    events = _events(_ask(client, live.id, option))
    assert _types(events) == ["accepted", "delta", "completed"]
    assert f"don’t have any marked answers to flag in {other.code}" in events[1]["text"]
    unavailable = _events(_ask(client, live.id, "Revise MISSING — Another subject"))
    assert unavailable[1]["text"].startswith("Which subject would you like to revise?")
    assert {e["prompt"] for e in unavailable if e["type"] == "follow_up"} == options
    assert tutor.model.prompts == tutor.model.embedded == []


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

    pauses = settings.ai_retry_pause_seconds * (2 ** (settings.ai_max_attempts - 1) - 1)
    assert settings.ai_max_attempts > 1 and pauses > 0
    assert tutor_chat.longest_exchange(settings) == (
        2 * settings.ai_queue_timeout_seconds
        + settings.ai_request_timeout_seconds * settings.ai_max_attempts
        + pauses
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


async def test_a_reader_who_leaves_while_the_model_writes_stops_it_at_once(db, tutor) -> None:
    """The student closes the chat while the model is still writing. The
    answer is vetted whole before any of it is sent, so they have only the
    acknowledgement; leaving has to reach the model through the guard."""
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
    assert json.loads(await anext(lines))["type"] == "accepted"
    reading = asyncio.ensure_future(anext(lines))
    async with asyncio.timeout(WAIT_SECONDS):
        await tutor.model.hanging.wait()
    assert tutor.model.streaming == 1
    # How a dropped connection reaches the response: its task is cancelled.
    reading.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reading
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


async def test_a_student_cannot_ask_when_the_lecturer_turned_the_assistant_off(
    db, app, tutor
) -> None:
    client, _, _ = db
    live = await _running_class(db, app)
    sign_in_as(app, LECTURER_ID, Role.LECTURER)
    switched = client.put(
        f"/api/v1/sessions/{live.id}/ai-controls", json={"learning_assistant": False}
    )
    assert switched.status_code == 200, switched.text
    sign_in_as(app, STUDENT_ID, Role.STUDENT)

    refused = _ask(client, live.id)

    assert refused.status_code == 403
    assert refused.json()["error"]["detail"]["reason"] == "learning_assistant_off"
    assert tutor.model.embedded == []
