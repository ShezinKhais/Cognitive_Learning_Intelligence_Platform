"""Validator tests. No model involved — we hand it deliberately broken
drafts and check each one is caught."""

import uuid

import pytest

from app.services.generation import DraftQuestion, build_prompt, parse_drafts, rejection_reasons
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
        prompt="What happens to the base layers in transfer learning?",
        options=["They are frozen", "They are deleted", "They are doubled", "They are shuffled"],
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

    assert drafts[0].options == []
    assert drafts[0].correct_option == -1


def test_non_array_output_is_rejected():
    with pytest.raises(ValueError):
        parse_drafts('{"prompt": "not in an array"}')


def test_prompt_includes_page_numbers_for_citation():
    text = build_prompt(chunks(), count=3)

    assert "[page 3]" in text
    assert "3 multiple-choice questions" in text
