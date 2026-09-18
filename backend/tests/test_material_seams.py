"""Draft question validation, the part of the seams with rules of its own.

Owner: General CS, Phase 2.
"""

from __future__ import annotations

import pytest

from app.schemas.content import Difficulty, QuestionType
from app.services.material_seams import DraftQuestion


@pytest.mark.parametrize(
    ("draft", "problem"),
    [
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "   ", ("A", "B"), 0), "no prompt"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A",), 0), "fewer than two"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), -1), "answer key"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), None), "answer key"),
        (DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Q?", (), 0), "free text"),
        (DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain."), None),
    ],
)
def test_draft_problems(draft: DraftQuestion, problem: str | None) -> None:
    found = draft.problem()
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


def test_a_draft_built_from_model_json_is_not_mistaken_for_free_text() -> None:
    """A generator parsing JSON passes "mcq", not QuestionType.MCQ."""
    draft = DraftQuestion("mcq", "easy", "Which?", ["A", "B"], 0)

    assert draft.type is QuestionType.MCQ
    assert draft.options == ("A", "B")
    assert draft.problem() is None


@pytest.mark.parametrize(
    ("draft", "problem"),
    [
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "B"), True), "answer key"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", " "), 0), "blank option"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, "Q?", ("A", "A"), 0), "repeats"),
        (DraftQuestion(QuestionType.MCQ, Difficulty.EASY, None, ("A", "B"), 0), "no prompt"),
        (
            DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain.", source_slide=0),
            "slide",
        ),
    ],
)
def test_more_draft_problems(draft: DraftQuestion, problem: str) -> None:
    found = draft.problem()
    assert found is not None and problem in found


@pytest.mark.parametrize(
    "draft",
    [
        DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain.", options=()),
        DraftQuestion(QuestionType.FREE_TEXT, Difficulty.EASY, "Explain.", correct_option=0),
    ],
)
def test_free_text_with_either_multiple_choice_field_is_refused(draft: DraftQuestion) -> None:
    assert "free text" in (draft.problem() or "")
