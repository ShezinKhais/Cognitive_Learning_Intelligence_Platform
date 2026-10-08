"""The before/after retrieval measures for #127, and the questions they are
asked with."""

import uuid
from pathlib import Path

import pytest

from app.services.extraction import ExtractedElement, chunk_elements
from app.services.image_captioning import CAPTION_PROMPT_VERSION, Caption, Outcome
from app.services.retrieval_evaluation import (
    CachedCaptioner,
    baseline_elements,
    cosine_ranking,
    first_relevant_rank,
    image_digest,
    load_queries,
    score,
)

EVAL_DIR = Path(__file__).parent / "eval"
SAMPLES = Path(__file__).parent / "samples"


def test_cosine_ranking_puts_the_nearest_first():
    assert cosine_ranking([1.0, 0.0], [[0.0, 1.0], [2.0, 0.1], [1.0, 1.0]]) == [1, 2, 0]


def test_cosine_ranking_ignores_length():
    assert cosine_ranking([1.0, 1.0], [[10.0, 0.0], [0.5, 0.5]]) == [1, 0]


def test_first_relevant_rank_counts_from_one():
    assert first_relevant_rank([4, 9, 9, 2], frozenset({9})) == 2
    assert first_relevant_rank([4, 9], frozenset({4, 9})) == 1


def test_a_page_with_no_chunk_is_never_found():
    assert first_relevant_rank([1, 2, 3], frozenset({9})) is None


def test_score_counts_misses_as_zero():
    result = score([1, 3, None, 6], k=5)

    assert result.queries == 4
    assert result.hit_at_1 == 0.25
    assert result.hit_at_k == 0.5
    assert result.mrr == pytest.approx((1 + 1 / 3 + 1 / 6) / 4)


def test_score_needs_queries():
    with pytest.raises(ValueError):
        score([])


def test_the_baseline_chunks_as_before_heading_levels():
    elements = [
        ExtractedElement("heading", "Chapter 2", 1, level=1),
        ExtractedElement("text", "Opening words.", 1),
        ExtractedElement("text", "Carried on.", 2),
    ]
    material_id = uuid.uuid4()

    now = chunk_elements(elements, material_id)
    before = chunk_elements(baseline_elements(elements), material_id)

    assert now[-1].chunk_text.startswith("Chapter 2\n")
    assert before[-1].chunk_text == "Carried on."


def test_the_baseline_drops_image_bytes():
    image = ExtractedElement("image", "[image on slide]", 3, image=b"png")

    assert baseline_elements([image])[0].image is None


class FakeCaptioner:
    model = "vision"
    max_images = 40

    def __init__(self, caption: Caption) -> None:
        self.reply = caption
        self.calls = 0

    async def describe(self, image: bytes) -> Caption:
        self.calls += 1
        return self.reply


async def test_a_cached_caption_is_not_asked_for_again():
    inner = FakeCaptioner(Caption(Outcome.CAPTIONED, "A falling S-curve.", sent=True))
    cache: dict[str, dict] = {}
    captioner = CachedCaptioner(inner, cache)

    first = await captioner.describe(b"image")
    second = await captioner.describe(b"image")

    assert inner.calls == 1
    assert first.text == second.text == "A falling S-curve."
    assert cache[image_digest(b"image")]["prompt"] == CAPTION_PROMPT_VERSION


@pytest.mark.parametrize(
    "stale", [{"model": "other"}, {"prompt": "caption-v0"}], ids=["model", "prompt"]
)
async def test_a_caption_from_another_model_or_prompt_is_redone(stale):
    entry = {
        "model": "vision",
        "prompt": CAPTION_PROMPT_VERSION,
        "outcome": "captioned",
        "text": "Old.",
    }
    cache = {image_digest(b"image"): entry | stale}
    inner = FakeCaptioner(Caption(Outcome.CAPTIONED, "New.", sent=True))

    caption = await CachedCaptioner(inner, cache).describe(b"image")

    assert (inner.calls, caption.text) == (1, "New.")


async def test_a_failed_caption_is_not_cached():
    inner = FakeCaptioner(Caption(Outcome.FAILED, sent=True))
    cache: dict[str, dict] = {}

    await CachedCaptioner(inner, cache).describe(b"image")

    assert cache == {}


def test_every_question_names_a_sample_and_a_page_in_it():
    queries = load_queries(EVAL_DIR / "retrieval_queries.json")

    assert queries
    for q in queries:
        assert (SAMPLES / q.material).exists(), q.material
        assert q.kind in {"image", "text"}
        assert q.pages and all(page >= 1 for page in q.pages)
    assert {q.kind for q in queries} == {"image", "text"}
