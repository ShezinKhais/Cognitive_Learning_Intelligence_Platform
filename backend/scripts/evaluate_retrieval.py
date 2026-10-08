"""Measures what #127 did for retrieval: the same questions, asked of each
sample material chunked before and after heading paths and image captions.

Not a test. Needs Ollama running with the embedding model and the caption
model from .env, and LibreOffice for the WMF pictures in lecture.pptx. Run
from backend/:

    python -m scripts.evaluate_retrieval
    python -m scripts.evaluate_retrieval --out tests/eval/RETRIEVAL_RESULTS.md

Captions are kept in tests/eval/caption_cache.json, so only the first run
waits for the vision model. Delete an entry, or change the caption prompt,
to caption that image again.

It prints, for each question, where the first chunk from a page that answers
it ranks before and after ("-" when the material had no chunk from that page
at all), then hit@1, hit@5 and MRR for picture and text questions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.services.ai_gateway import GatewayEmbeddingClient, Priority, get_ai_gateway
from app.services.embeddings import BATCH_SIZE
from app.services.extraction import ContentChunk, chunk_elements, process_material
from app.services.image_captioning import (
    CAPTION_PROMPT_VERSION,
    ImageCaptioner,
    VectorConverter,
    add_captions,
    find_libreoffice,
)
from app.services.retrieval_evaluation import (
    TOP_K,
    CachedCaptioner,
    RetrievalQuery,
    RetrievalScore,
    baseline_elements,
    cosine_ranking,
    first_relevant_rank,
    load_queries,
    score,
)

BACKEND = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND / "tests" / "eval"
SAMPLES = BACKEND / "tests" / "samples"
CONDITIONS = ("before", "after")


async def embed_all(client: GatewayEmbeddingClient, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        vectors.extend(await client.embed(texts[start : start + BATCH_SIZE]))
    return vectors


async def chunk_both_ways(
    material: str, captioner: CachedCaptioner
) -> dict[str, list[ContentChunk]]:
    material_id = uuid.uuid4()
    result = process_material(str(SAMPLES / material), material_id, with_images=True)
    captioned, report = await add_captions(result, captioner)
    print(
        f"{material}: {result.parser_used}, {report.captioned} image(s) captioned, "
        f"{report.failed} failed, {report.unsupported} unsupported"
    )
    return {
        "before": chunk_elements(baseline_elements(result.elements), material_id),
        "after": captioned.chunks,
    }


def table(
    queries: list[RetrievalQuery], ranks: dict[str, list[int | None]], tops: dict[str, list[int]]
) -> list[str]:
    def shown(rank: int | None) -> str:
        return "-" if rank is None else str(rank)

    lines = [
        "| Kind | Question | Answer on | Before: rank (top page) | After: rank (top page) |",
        "|---|---|---|---|---|",
    ]
    for i, q in enumerate(queries):
        pages = ", ".join(str(p) for p in sorted(q.pages))
        cells = [f"{shown(ranks[c][i])} ({tops[c][i]})" for c in CONDITIONS]
        lines.append(f"| {q.kind} | {q.query} | {pages} | {cells[0]} | {cells[1]} |")
    return lines


def summary(queries: list[RetrievalQuery], ranks: dict[str, list[int | None]]) -> list[str]:
    def row(name: str, before: RetrievalScore, after: RetrievalScore) -> str:
        cells = [
            f"{before.hit_at_1:.2f} → {after.hit_at_1:.2f}",
            f"{before.hit_at_k:.2f} → {after.hit_at_k:.2f}",
            f"{before.mrr:.2f} → {after.mrr:.2f}",
        ]
        return f"| {name} ({before.queries}) | " + " | ".join(cells) + " |"

    lines = [
        f"| Questions | hit@1 | hit@{TOP_K} | MRR |",
        "|---|---|---|---|",
    ]
    groups = [
        (kind, [i for i, q in enumerate(queries) if q.kind == kind]) for kind in ("image", "text")
    ]
    groups.append(("all", list(range(len(queries)))))
    for name, members in groups:
        if members:
            by = {c: score([ranks[c][i] for i in members]) for c in CONDITIONS}
            lines.append(row(name, by["before"], by["after"]))
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queries", type=Path, default=EVAL_DIR / "retrieval_queries.json")
    parser.add_argument("--captions", type=Path, default=EVAL_DIR / "caption_cache.json")
    parser.add_argument("--out", type=Path, help="also write the results as Markdown")
    args = parser.parse_args()

    settings = get_settings()
    gateway = get_ai_gateway()
    embedder = GatewayEmbeddingClient(gateway, "retrieval-evaluation", priority=Priority.BACKGROUND)
    office = find_libreoffice(settings.libreoffice_path)
    if office is None:
        print("LibreOffice not found: WMF and EMF pictures will not be captioned.")
    cache = json.loads(args.captions.read_text()) if args.captions.exists() else {}
    captioner = CachedCaptioner(
        ImageCaptioner(
            gateway,
            settings.image_caption_model,
            timeout=settings.image_caption_timeout_seconds,
            converter=VectorConverter(office) if office else None,
        ),
        cache,
    )

    queries = load_queries(args.queries)
    ranks: dict[str, list[int | None]] = {c: [] for c in CONDITIONS}
    tops: dict[str, list[int]] = {c: [] for c in CONDITIONS}
    try:
        for material in dict.fromkeys(q.material for q in queries):
            asked = [q for q in queries if q.material == material]
            chunks = await chunk_both_ways(material, captioner)
            args.captions.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
            query_vectors = await embed_all(embedder, [q.query for q in asked])
            for condition in CONDITIONS:
                found = chunks[condition]
                vectors = await embed_all(embedder, [c.chunk_text for c in found])
                for q, query_vector in zip(asked, query_vectors, strict=True):
                    pages = [found[i].source_page for i in cosine_ranking(query_vector, vectors)]
                    ranks[condition].append(first_relevant_rank(pages, q.pages))
                    tops[condition].append(pages[0])
    finally:
        await gateway.shutdown()

    # Results are gathered material by material, so put the questions in the
    # same order.
    ordered = [
        q for m in dict.fromkeys(q.material for q in queries) for q in queries if q.material == m
    ]
    report = [
        "# Retrieval before and after #127",
        "",
        f"Embedding model `{settings.embedding_model}`, captions by "
        f"`{captioner.model}` with prompt `{CAPTION_PROMPT_VERSION}`. "
        "Rank is where the first chunk from a page that answers the question "
        "comes; `-` means the material had no chunk from that page at all.",
        "",
        *summary(ordered, ranks),
        "",
        *table(ordered, ranks, tops),
    ]
    print("\n" + "\n".join(report))
    if args.out:
        args.out.write_text("\n".join(report) + "\n")
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
