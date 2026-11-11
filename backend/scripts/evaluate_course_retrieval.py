"""Whether the tutor's search finds the right page, course by course, and
stays quiet when no page answers (#252).

Not a test. Needs Ollama running with the embedding model in .env (and the
caption model when IMAGE_CAPTIONING_ENABLED is on). Run from backend/:

    python -m scripts.evaluate_course_retrieval --materials ~/clip-pilot \
        --out ~/clip-pilot/retrieval/RETRIEVAL_COURSES.md

Each course's files are read, captioned and chunked as an upload does, every
chunk is embedded with the app's embedding model, and each question searches
all of its course's chunks together, as the tutor does. The lecture files stay
outside the repository; the report records each one's SHA-256 so a rerun can
be checked against the same files. Captions are kept in the materials folder
(caption_cache.json), so only the first run waits for the vision model.

The questions are in tests/eval/retrieval_courses/queries.json, and
tests/eval/retrieval_courses/README.md says how to write held-out ones.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.services.ai_gateway import (
    AiUnavailableError,
    GatewayEmbeddingClient,
    Priority,
    get_ai_gateway,
)
from app.services.course_retrieval_evaluation import (
    Excerpt,
    Result,
    load_query_set,
    report,
    search,
)
from app.services.extraction import extract_material, finish_material
from app.services.image_captioning import CAPTION_PROMPT_VERSION, ImageCaptioner, add_captions
from app.services.processing_security import validate_extraction
from app.services.retrieval_evaluation import CachedCaptioner
from app.services.tutor_guardrails import RETRIEVAL_MAX_DISTANCE
from app.services.uploads import MATERIAL_QUEUE_TIMEOUT_SECONDS, _ocr_reader, _vector_converter
from scripts.evaluate_retrieval import embed_all

BACKEND = Path(__file__).resolve().parent.parent
QUERIES = BACKEND / "tests" / "eval" / "retrieval_courses" / "queries.json"


def commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=BACKEND, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        return git("rev-parse", "--short", "HEAD") + (
            " with uncommitted changes" if git("status", "--porcelain", "-uno") else ""
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def main(args: argparse.Namespace) -> None:
    courses, queries = load_query_set(args.queries)
    wanted = {c for c in (q.course for q in queries)}
    missing = sorted(f for c in wanted for f in courses[c] if not (args.materials / f).is_file())
    if missing:
        raise SystemExit(f"Not in {args.materials}: {', '.join(missing)}")

    settings = get_settings()
    gateway = get_ai_gateway()
    embedder = GatewayEmbeddingClient(gateway, "retrieval-evaluation", priority=Priority.BACKGROUND)
    cache_path = args.materials / "caption_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    captioner = (
        CachedCaptioner(
            ImageCaptioner(
                gateway,
                settings.image_caption_model,
                timeout=settings.image_caption_timeout_seconds,
                queue_timeout=MATERIAL_QUEUE_TIMEOUT_SECONDS,
                max_images=settings.image_caption_max_images,
                converter=_vector_converter(settings.libreoffice_path),
            ),
            cache,
        )
        if settings.image_captioning_enabled
        else None
    )
    reader = _ocr_reader(settings)

    results: list[Result] = []
    material_rows: list[str] = []
    try:
        for course in dict.fromkeys(q.course for q in queries):
            excerpts: list[Excerpt] = []
            for name in courses[course]:
                path = args.materials / name
                material_id = uuid.uuid4()
                extraction = extract_material(
                    str(path),
                    settings.max_upload_bytes,
                    with_images=captioner is not None,
                    ocr=reader.read if reader is not None else None,
                )
                validate_extraction(extraction.elements, settings)
                if captioner is not None and any(e.image for e in extraction.elements):
                    elements, _ = await add_captions(extraction.elements, captioner, material_id)
                    extraction = replace(extraction, elements=elements)
                    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
                chunks = finish_material(extraction, material_id).chunks
                vectors = await embed_all(embedder, [c.chunk_text for c in chunks])
                excerpts += [
                    Excerpt(name, c.source_page, tuple(v))
                    for c, v in zip(chunks, vectors, strict=True)
                ]
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
                material_rows.append(
                    f"| {course} | {name} | `{digest}` | {extraction.parser_used} | {len(chunks)} |"
                )
                print(f"{course}: {name}, {len(chunks)} chunks")
            asked = [q for q in queries if q.course == course]
            query_vectors = await embed_all(embedder, [q.query for q in asked])
            results += [
                Result(q, tuple(search(v, excerpts)))
                for q, v in zip(asked, query_vectors, strict=True)
            ]
    except AiUnavailableError:
        raise SystemExit(
            f"The model server at {settings.ollama_base_url} did not answer. Is Ollama "
            f"running, with {settings.embedding_model} pulled? Nothing was written."
        ) from None
    finally:
        await gateway.shutdown()

    captions = (
        f"captions by `{settings.image_caption_model}` (prompt `{CAPTION_PROMPT_VERSION}`)"
        if captioner is not None
        else "image captioning off"
    )
    header = [
        "# Retrieval across whole courses (#252)",
        "",
        f"Embedding model `{settings.embedding_model}`, {captions}, commit `{commit()}`, "
        f"run on {date.today().isoformat()}. Each question searches every chunk of its "
        f"course, as the tutor does. The tutor's cutoff is now {RETRIEVAL_MAX_DISTANCE:.2f}.",
        "",
        "| Course | Material | SHA-256 (first 12) | Read with | Chunks |",
        "|---|---|---|---|---|",
        *material_rows,
    ]
    text = report(results, header=header)
    print("\n" + text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"written to {args.out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queries", type=Path, default=QUERIES)
    parser.add_argument(
        "--materials", type=Path, required=True, help="the folder holding the course files"
    )
    parser.add_argument("--out", type=Path, help="also write the report here")
    asyncio.run(main(parser.parse_args()))
