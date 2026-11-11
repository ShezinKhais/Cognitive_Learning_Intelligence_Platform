"""Opt-in tutor and free-text marking load during an isolated live class."""

import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.comprehension_result import ComprehensionResult
from app.models.material import Material
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.student_response import StudentResponse
from scripts.loadtest.environment import Person, sessions
from scripts.loadtest.scenarios.common import FAN_OUT_LIMIT_SECONDS, Classroom, Result, spread

PASSAGE = (
    "During photosynthesis chlorophyll absorbs light. Plants use that light energy "
    "to turn water and carbon dioxide into sugars, and oxygen is released."
)
TUTOR_QUESTION = "How do plants use sunlight during photosynthesis?"


async def _seed_model_work(room: Classroom, settings: Settings) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.ollama_base_url.rstrip('/')}/embeddings",
            json={"model": settings.embedding_model, "input": [PASSAGE]},
        )
        response.raise_for_status()
        embedding = response.json()["data"][0]["embedding"]

    async with sessions(room.database)() as db:
        material = await db.scalar(
            select(Material).where(Material.course_id == room.seeded.course_id)
        )
        assert material is not None
        db.add(
            RagChunk(
                source_material_id=material.id,
                chunk_index=0,
                source_page=1,
                chunk_text=PASSAGE,
                embedding_model=settings.embedding_model,
                embedding_vector=embedding,
            )
        )
        question = Question(
            source_material_id=material.id,
            question_text="Explain why the Moon looks bright at night.",
            question_type="free_text",
            status="staged",
            reference_answer="The Moon reflects light from the Sun.",
            key_points=["It reflects light from the Sun."],
        )
        db.add(question)
        await db.commit()
        return str(question.question_id)


async def _chat(room: Classroom, person: Person) -> tuple[float | None, float, str]:
    started = time.perf_counter()
    first = None
    terminal = "incomplete"
    try:
        async with (
            room.http(person) as client,
            client.stream(
                "POST",
                f"/sessions/{room.session_id}/chat",
                json={"request_id": "live-ai-load", "question": TUTOR_QUESTION},
            ) as response,
        ):
            if response.status_code != 200:
                return first, time.perf_counter() - started, str(response.status_code)
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                kind = event["type"]
                if kind == "delta" and event.get("text") and first is None:
                    first = time.perf_counter() - started
                if kind in {"completed", "unsupported", "empty_retrieval", "error"}:
                    terminal = kind
    except httpx.HTTPError as exc:
        terminal = type(exc).__name__
    return first, time.perf_counter() - started, terminal


async def live_ai_load(room: Classroom, settings: Settings, chatters: int) -> Result:
    result = Result("live-ai", "Tutor streams and free-text marking during a live class")
    question_id = await _seed_model_work(room, settings)
    chat_students = room.students[:chatters]
    room.seeded.questions.insert(0, question_id)
    async with asyncio.TaskGroup() as group:
        chats = [group.create_task(_chat(room, student.person)) for student in chat_students]
        _, arrivals, _ = await room.deliver()
        submitted_at = datetime.now(UTC)
        receipts = await asyncio.gather(
            *(
                student.answer(question_id, free_text="It reflects sunlight.")
                for student in room.students
            )
        )
        closed = await room.closed(question_id)

    replies = [task.result() for task in chats]
    result.figures["generation_model"] = settings.ollama_model
    result.figures["embedding_model"] = settings.embedding_model
    result.figures["model_concurrency"] = settings.ai_max_concurrency
    result.figures["model_queue_limit"] = settings.ai_queue_limit
    result.figures["chat_first_token"] = spread(
        [first for first, _, _ in replies if first is not None]
    )
    result.figures["chat_complete"] = spread(
        [elapsed for _, elapsed, terminal in replies if terminal == "completed"]
    )
    result.figures["chat_endings"] = [terminal for _, _, terminal in replies]
    result.figures["checkpoint_fan_out"] = spread(arrivals)
    result.figures["checkpoint_receipts"] = spread(
        [receipt for receipt in receipts if receipt is not None]
    )
    result.check(
        "all tutor requests streamed a reply",
        all(first is not None and terminal == "completed" for first, _, terminal in replies),
        result.figures["chat_endings"],
    )
    result.check(
        "all connected students received and answered the checkpoint",
        max(arrivals) <= FAN_OUT_LIMIT_SECONDS
        and all(receipt is not None for receipt in receipts)
        and closed["respondents"] == len(room.students),
        closed["respondents"],
    )

    marked = 0
    last_mark = None
    until = time.monotonic() + 60
    query = (
        select(func.count(), func.max(ComprehensionResult.created_at))
        .select_from(ComprehensionResult)
        .join(StudentResponse, StudentResponse.response_id == ComprehensionResult.response_id)
        .where(
            StudentResponse.question_id == question_id,
            ComprehensionResult.model_name.is_not(None),
        )
    )
    async with sessions(room.database)() as db:
        while time.monotonic() < until:
            marked, last_mark = (await db.execute(query)).one()
            if marked == len(room.students):
                break
            await asyncio.sleep(0.5)
    result.figures["model_marks"] = marked
    if last_mark is not None:
        result.figures["last_mark_seconds"] = round((last_mark - submitted_at).total_seconds(), 2)
    result.check(
        "all submitted answers received a model mark", marked == len(room.students), marked
    )
    return result
