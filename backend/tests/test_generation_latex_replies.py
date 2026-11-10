"""Replies whose LaTeX backslashes are not JSON escapes (#267). Owner: AI 1.

One such backslash made json.loads fail, and the whole reply, every draft in
it, was thrown away.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.services.generation import (
    QuestionGenerator,
    escape_stray_backslashes,
    parse_drafts,
    rejection_reasons,
)
from app.services.retrieval import RetrievedChunk

# The start of the reply the practice round lost: a lone "\(" next to an
# escaped "\\hat", as qwen2.5:3b wrote it for the MIT 18.650 regression slides.
LATEX = r"""[
  {"prompt": "In linear regression, what does \(\\hat{a}\\) represent in \(y = \\hat{a}\)?",
   "options": ["The intercept", "The slope", "The correlation", "The variance"],
   "correct_option": 0, "topic": "Regression", "source_slide": 12,
   "source_excerpt": "the intercept a is estimated by the least squares estimator"},
  {"prompt": "What does least squares minimise?",
   "options": ["The sum of squared errors", "The mean", "The slope", "The variance"],
   "correct_option": 0, "topic": "Regression", "source_slide": 12,
   "source_excerpt": "minimizer of the sum of squared errors"}
]"""


def test_a_reply_with_latex_backslashes_keeps_all_its_drafts():
    drafts = parse_drafts(LATEX)
    assert len(drafts) == 2
    # The backslashes read as the model wrote them.
    assert drafts[0].prompt.startswith(r"In linear regression, what does \(\hat{a}\) represent")
    assert drafts[1].prompt == "What does least squares minimise?"


@pytest.mark.parametrize(
    ("written", "read"),
    [
        (r'"\(x\)"', r"\(x\)"),
        (r'"\sigma"', r"\sigma"),
        # Already escaped: one backslash, then "(".
        (r'"\\(x\\)"', r"\(x\)"),
        # Real escapes are left alone.
        (r'"line\nbreak \"quoted\" \/ \u00e9"', 'line\nbreak "quoted" / é'),
        # A \u without four hex digits is not an escape.
        (r'"\u12"', r"\u12"),
    ],
)
def test_each_backslash_reads_as_written(written, read):
    assert json.loads(escape_stray_backslashes(written)) == read


def test_a_reply_broken_another_way_is_still_rejected():
    with pytest.raises(ValueError, match="valid JSON"):
        parse_drafts(r'[{"prompt": "What is \(x\)?", "options": ["a", "b"')
    with pytest.raises(ValueError, match="valid JSON"):
        parse_drafts("Rebellion")


def test_a_repaired_draft_still_goes_through_every_check():
    chunks = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            chunk_text="Linear regression. The least squares estimator is the minimizer of the "
            "sum of squared errors.",
            source_page=3,
            distance=0.1,
        )
    ]
    (draft, _) = parse_drafts(LATEX)
    # Cites slide 12, which these chunks do not have.
    assert rejection_reasons(draft, chunks)


class FakeChatClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.chat = self

    @property
    def completions(self):
        return self

    async def create(self, model, messages, **kwargs):
        from types import SimpleNamespace

        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


async def test_the_generator_no_longer_loses_the_reply():
    chunks = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            chunk_text="Linear regression of Y on X. The least squares estimator of the "
            "intercept a is the minimizer of the sum of squared errors.",
            source_page=12,
            distance=0.1,
        )
    ]
    outcome = await QuestionGenerator(FakeChatClient(LATEX), "test-model")._draft(chunks)
    assert len(outcome.accepted) + len(outcome.rejected) == 2
