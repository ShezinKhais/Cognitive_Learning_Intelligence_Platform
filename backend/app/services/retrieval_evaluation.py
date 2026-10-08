"""Whether retrieval finds the right page, before and after #127.

Owner: AI 1, Phase 6 (#127). The same questions are asked of a material
chunked the old way (headings without levels, images left as placeholders)
and the new way (heading paths and image captions), and each answer is scored
by where the first chunk from a page that answers it ranks. Plain functions,
so they need no model; scripts/evaluate_retrieval.py runs them against one.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from app.services.extraction import ExtractedElement
from app.services.image_captioning import CAPTION_PROMPT_VERSION, Caption, Outcome

# What the retriever hands back by default (ChunkRetriever.search).
TOP_K = 5


@dataclass(frozen=True)
class RetrievalQuery:
    material: str  # a file in tests/samples
    query: str
    pages: frozenset[int]  # the pages or slides that answer it
    # "image" when only a picture answers it, "text" when the page's text
    # does. Text questions check that captions do not crowd out text.
    kind: str


def load_queries(path: Path) -> list[RetrievalQuery]:
    return [
        RetrievalQuery(
            material=item["material"],
            query=item["query"],
            pages=frozenset(item["pages"]),
            kind=item["kind"],
        )
        for item in json.loads(path.read_text())
    ]


def baseline_elements(elements: Sequence[ExtractedElement]) -> list[ExtractedElement]:
    """The elements as chunking saw them before #127: every heading applies to
    its own page only, and no image has a caption."""
    return [replace(e, level=0, image=None) for e in elements]


def cosine_ranking(query: Sequence[float], vectors: Sequence[Sequence[float]]) -> list[int]:
    """Indexes of `vectors`, nearest to `query` first, as pgvector's cosine
    distance orders them. Ties keep their order."""

    def similarity(vector: Sequence[float]) -> float:
        norms = math.sqrt(sum(q * q for q in query)) * math.sqrt(sum(v * v for v in vector))
        return sum(q * v for q, v in zip(query, vector, strict=True)) / norms if norms else 0.0

    scores = [similarity(v) for v in vectors]
    return sorted(range(len(vectors)), key=lambda i: -scores[i])


def first_relevant_rank(ranked_pages: Sequence[int], relevant: frozenset[int]) -> int | None:
    """1-based rank of the first chunk from a relevant page, or None if no
    chunk comes from one: the material has nothing on that page to find."""
    for rank, page in enumerate(ranked_pages, start=1):
        if page in relevant:
            return rank
    return None


@dataclass(frozen=True)
class RetrievalScore:
    queries: int
    hit_at_1: float  # share answered by the top chunk
    hit_at_k: float  # share answered within the top TOP_K
    mrr: float  # mean of 1/rank, 0 for a miss


def score(ranks: Sequence[int | None], k: int = TOP_K) -> RetrievalScore:
    if not ranks:
        raise ValueError("no queries to score")
    n = len(ranks)
    return RetrievalScore(
        queries=n,
        hit_at_1=sum(r == 1 for r in ranks) / n,
        hit_at_k=sum(r is not None and r <= k for r in ranks) / n,
        mrr=sum(1 / r for r in ranks if r is not None) / n,
    )


def image_digest(image: bytes) -> str:
    return hashlib.sha256(image).hexdigest()


class CachedCaptioner:
    """A captioner that remembers its captions, so a rerun does not wait a
    minute an image for the vision model.

    A cached caption is reused only if the same model and prompt wrote it.
    Failures are not cached, so a rerun tries them again.
    """

    def __init__(self, captioner, cache: dict[str, dict]) -> None:
        self._captioner = captioner
        self.model = captioner.model
        self.max_images = captioner.max_images
        self.cache = cache

    async def describe(self, image: bytes) -> Caption:
        key = image_digest(image)
        found = self.cache.get(key)
        if found and found["model"] == self.model and found["prompt"] == CAPTION_PROMPT_VERSION:
            return Caption(Outcome(found["outcome"]), found["text"])
        caption = await self._captioner.describe(image)
        if caption.outcome is not Outcome.FAILED:
            self.cache[key] = {
                "model": self.model,
                "prompt": CAPTION_PROMPT_VERSION,
                "outcome": caption.outcome.value,
                "text": caption.text,
            }
        return caption
