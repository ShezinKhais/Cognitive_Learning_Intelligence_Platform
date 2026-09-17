"""Validator tests. No model involved — we hand it deliberately broken
drafts and check each one is caught."""

import uuid

import pytest

from app.schemas.content import Difficulty, QuestionType
from app.services.generation import (
    MAX_PROMPT_CHUNKS,
    QuestionGenerator,
    build_prompt,
    parse_drafts,
    rejection_reasons,
)
from app.services.material_seams import DraftQuestion
from app.services.retrieval import RetrievedChunk

CHUNK_TEXT = (
    "Transfer learning reuses a network trained on a large dataset. "
    "The base layers are frozen so their weights do not change during training."
)


def chunks():
    return [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            chunk_text=CHUNK_TEXT,
            source_page=3,
            distance=0.1,
        )
    ]


def draft(**overrides):
    """A valid draft, unless a test overrides one field to break it."""
    base = dict(
        type=QuestionType.MCQ,
        difficulty=Difficulty.MEDIUM,
        prompt="What happens to the base layers in transfer learning?",
        options=("They are frozen", "They are deleted", "They are doubled", "They are shuffled"),
        correct_option=0,
        topic="Transfer learning",
        source_slide=3,
        source_excerpt="the base layers are frozen so their weights do not change",
    )
    base.update(overrides)
    return DraftQuestion(**base)


def test_a_good_draft_has_no_reasons():
    assert rejection_reasons(draft(), chunks()) == []


def test_catches_wrong_option_count():
    reasons = rejection_reasons(draft(options=["a", "b", "c"]), chunks())
    assert any("options" in r for r in reasons)


def test_catches_correct_option_out_of_range():
    reasons = rejection_reasons(draft(correct_option=7), chunks())
    assert any("out of range" in r for r in reasons)


def test_catches_duplicate_options():
    reasons = rejection_reasons(draft(options=["frozen", "frozen", "deleted", "doubled"]), chunks())
    assert any("duplicates" in r for r in reasons)


def test_catches_invented_page_number():
    reasons = rejection_reasons(draft(source_slide=12), chunks())
    assert any("cites page 12" in r for r in reasons)


def test_catches_ungrounded_excerpt():
    """The hallucination case: fluent, plausible, and not in the material."""
    reasons = rejection_reasons(
        draft(source_excerpt="Gradient descent converges faster with momentum"),
        chunks(),
    )
    assert any("not grounded" in r for r in reasons)


def test_parses_a_clean_json_array():
    raw = (
        '[{"prompt": "Q?", "options": ["a","b","c","d"], "correct_option": 1,'
        ' "topic": "T", "source_slide": 3, "source_excerpt": "x"}]'
    )

    drafts = parse_drafts(raw)

    assert len(drafts) == 1
    assert drafts[0].correct_option == 1


def test_strips_markdown_fences():
    """Models wrap JSON in fences often enough that this can't be optional."""
    raw = (
        '```json\n[{"prompt": "Q?", "options": ["a","b","c","d"],'
        ' "correct_option": 0, "topic": "T", "source_slide": 3,'
        ' "source_excerpt": "x"}]\n```'
    )

    drafts = parse_drafts(raw)

    assert len(drafts) == 1


def test_missing_fields_become_a_rejectable_draft_not_a_crash():
    """A malformed item must survive parsing so the validator can explain it."""
    drafts = parse_drafts('[{"prompt": "Q?"}]')

    assert drafts[0].options == ()
    assert drafts[0].correct_option == -1


def test_non_array_output_is_rejected():
    with pytest.raises(ValueError):
        parse_drafts('{"prompt": "not in an array"}')


def test_prompt_includes_page_numbers_for_citation():
    text = build_prompt(chunks(), count=3)

    assert "[page 3]" in text
    assert "3 multiple-choice questions" in text


def test_prompt_samples_chunks_across_the_whole_material():
    many_chunks = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=i,
            chunk_text=f"Content from page {i + 1}",
            source_page=i + 1,
            distance=0.1,
        )
        for i in range(60)
    ]

    text = build_prompt(many_chunks, count=5)

    assert "[page 1]" in text
    assert "[page 60]" in text
    assert text.count("[page ") == MAX_PROMPT_CHUNKS


def test_page_number_returned_as_a_string_is_still_a_number():
    """Qwen returns source_slide as "3" rather than 3."""
    raw = (
        '[{"prompt": "Q?", "options": ["a","b","c","d"], "correct_option": 0,'
        ' "topic": "T", "source_slide": "3", "source_excerpt": "x"}]'
    )

    assert parse_drafts(raw)[0].source_slide == 3


def test_catches_options_that_are_reorderings():
    """Observed in a real generation run: same words, different order."""
    reasons = rejection_reasons(
        draft(
            options=[
                "Retraining happens only in the base layers",
                "Retraining happens in the base layers only",
                "Retraining happens in the output layer",
                "Retraining happens everywhere",
            ]
        ),
        chunks(),
    )
    assert any("reorderings" in r for r in reasons)


class FakeChatClient:
    def __init__(self, content):
        self._content = content
        self.chat = self

    @property
    def completions(self):
        return self

    async def create(self, model, messages):
        class M:
            content = self._content

        class C:
            message = M()

        class R:
            choices = [C()]

        return R()


def test_catches_excerpt_quoted_from_a_page_it_did_not_cite():
    """Citing page 3 while quoting page 9 passed before: the page check and the
    excerpt check ran independently."""
    other_page = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        chunk_index=1,
        chunk_text="Dropout randomly disables neurons during training.",
        source_page=9,
        distance=0.2,
    )

    reasons = rejection_reasons(
        draft(
            source_slide=3,
            source_excerpt="Dropout randomly disables neurons during training",
        ),
        chunks() + [other_page],
    )

    assert any("not grounded" in r for r in reasons)


def test_a_null_array_member_becomes_a_rejectable_draft():
    drafts = parse_drafts("[null]")

    assert len(drafts) == 1
    assert rejection_reasons(drafts[0], chunks())


def test_non_numeric_fields_do_not_abort_the_batch():
    """One malformed item used to raise and lose every other question."""
    raw = (
        '[{"prompt": "Q?", "options": null, "correct_option": "abc",'
        ' "source_slide": "page three", "source_excerpt": "x"}]'
    )

    drafts = parse_drafts(raw)

    assert drafts[0].correct_option == -1
    assert drafts[0].source_slide is None
    assert drafts[0].options == ()


def test_boolean_correct_option_is_rejected():
    raw = (
        '[{"prompt": "Q?", "options": ["a","b","c","d"], "correct_option": true,'
        ' "topic": "T", "source_slide": 3, "source_excerpt": "x"}]'
    )

    parsed = parse_drafts(raw)

    assert parsed[0].correct_option == -1


def test_boolean_source_slide_is_rejected():
    raw = (
        '[{"prompt": "Q?", "options": ["a","b","c","d"], "correct_option": 0,'
        ' "topic": "T", "source_slide": true, "source_excerpt": "x"}]'
    )

    parsed = parse_drafts(raw)

    assert parsed[0].source_slide is None


def test_non_string_prompt_becomes_rejectable_draft():
    raw = (
        '[{"prompt": {"text": "Q?"}, "options": ["a","b","c","d"],'
        ' "correct_option": 0, "topic": "T", "source_slide": 3,'
        ' "source_excerpt": "x"}]'
    )

    parsed = parse_drafts(raw)

    assert parsed[0].prompt == ""
    assert any("prompt is empty" in r for r in rejection_reasons(parsed[0], chunks()))


def test_non_string_source_excerpt_becomes_rejectable_draft():
    raw = (
        '[{"prompt": "Q?", "options": ["a","b","c","d"],'
        ' "correct_option": 0, "topic": "T", "source_slide": 3,'
        ' "source_excerpt": {"text": "x"}}]'
    )

    parsed = parse_drafts(raw)

    assert parsed[0].source_excerpt is None
    assert any("no source excerpt" in r for r in rejection_reasons(parsed[0], chunks()))


async def test_generator_separates_accepted_from_rejected():
    good = (
        '{"prompt": "What happens to the base layers?",'
        ' "options": ["They are frozen", "Deleted", "Doubled", "Shuffled"],'
        ' "correct_option": 0, "topic": "T", "source_slide": 3,'
        ' "source_excerpt": "the base layers are frozen"}'
    )
    bad = (
        '{"prompt": "Invented?", "options": ["a","b","c","d"],'
        ' "correct_option": 0, "topic": "T", "source_slide": 3,'
        ' "source_excerpt": "Gradient descent converges faster with momentum"}'
    )
    generator = QuestionGenerator(FakeChatClient(f"[{good},{bad}]"), "test-model")

    outcome = await generator._draft(chunks())

    assert len(outcome.accepted) == 1
    assert len(outcome.rejected) == 1


async def test_generate_returns_only_accepted_drafts():
    good = (
        '{"prompt": "What happens to the base layers?",'
        ' "options": ["They are frozen", "Deleted", "Doubled", "Shuffled"],'
        ' "correct_option": 0, "topic": "T", "source_slide": 3,'
        ' "source_excerpt": "the base layers are frozen"}'
    )
    generator = QuestionGenerator(FakeChatClient(f"[{good}]"), "test-model")

    drafts = await generator.generate(uuid.uuid4(), chunks())

    assert len(drafts) == 1


async def test_generator_returns_nothing_without_chunks():
    generator = QuestionGenerator(FakeChatClient("[]"), "test-model")

    assert await generator.generate(uuid.uuid4(), []) == []


def test_catches_an_answer_the_excerpt_does_not_support():
    """The hallucination that survives grounding: a real quote from the right
    page, paired with an answer that quote says nothing about."""
    reasons = rejection_reasons(
        draft(
            prompt="What is the main advantage of freezing the base layers?",
            options=("Lower memory use", "More layers", "Faster hardware", "Bigger datasets"),
            correct_option=0,
            source_excerpt="the base layers are frozen so their weights do not change",
        ),
        chunks(),
    )

    assert any("little overlap" in r for r in reasons)


def test_truncated_json_raises_value_error_not_a_decode_error():
    """Local models truncate. The caller expects ValueError, not whatever
    json.loads happens to raise."""
    with pytest.raises(ValueError):
        parse_drafts('[{"prompt": "Q?", "options": ["a","b"')


async def test_unparseable_output_costs_the_batch_not_the_material():
    """A truncated or chatty reply should lose this batch, not fail the upload."""
    generator = QuestionGenerator(
        FakeChatClient("Here are your questions: [{'prompt': "), "test-model"
    )

    drafts = await generator.generate(uuid.uuid4(), chunks())

    assert drafts == []


def test_prompt_is_bounded_regardless_of_material_size():
    """qwen2.5:3b has a 4096-token window. 200 chunks would truncate silently."""
    many = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=i,
            chunk_text=f"Chunk number {i}. " * 30,
            source_page=i + 1,
            distance=0.1,
        )
        for i in range(200)
    ]

    text = build_prompt(many, count=5)

    assert "[page 13]" not in text
    assert len(text) < 10_000
