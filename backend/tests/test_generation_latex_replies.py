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
        # Quote, slash and \u escapes are left alone.
        (r'"\"quoted\" \/ \u00e9"', '"quoted" / é'),
        # \b \f \n \r \t start LaTeX commands, so they read as written (#272).
        (
            r'"\frac{a}{b} \theta \beta \nabla \right \times \neq \text"',
            r"\frac{a}{b} \theta \beta \nabla \right \times \neq \text",
        ),
        # A \u without four hex digits is not an escape.
        (r'"\u12"', r"\u12"),
    ],
)
def test_each_backslash_reads_as_written(written, read):
    assert json.loads(escape_stray_backslashes(written)) == read


def reply(prompt: str) -> str:
    return (
        '[{"prompt": "' + prompt + '", "options": ["1", "2", "3", "4"], '
        '"correct_option": 0, "topic": "Calculus", "source_slide": 3, '
        '"source_excerpt": "the derivative of a quotient"}]'
    )


def test_a_repaired_reply_keeps_latex_that_looks_like_json_escapes():
    # The stray "\(" makes the first read fail; "\frac" must not become a
    # form feed and "rac" when the reply is repaired.
    drafts = parse_drafts(reply(r"What is \(\frac{a}{b}\) when \theta = 0?"))
    assert drafts[0].prompt == r"What is \(\frac{a}{b}\) when \theta = 0?"


@pytest.mark.parametrize(
    "latex",
    [r"\frac{a}{b}", r"\theta", r"\beta", r"\nabla", r"\right)", r"\times", r"\neq", r"\text{x}"],
)
def test_latex_is_kept_even_when_the_reply_parses_first_time(latex):
    # Each of these is valid JSON, so the first read succeeds but decodes
    # "\f", "\t", "\b", "\n" or "\r"; the reply is read again as written.
    prompt = f"Is {latex} defined here?"
    assert parse_drafts(reply(prompt))[0].prompt == prompt


def test_a_real_line_break_before_a_capital_is_kept():
    drafts = parse_drafts(reply(r"First line.\nSecond line?"))
    assert drafts[0].prompt == "First line.\nSecond line?"


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
