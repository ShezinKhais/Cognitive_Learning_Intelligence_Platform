"""Questions answered by a value looked up in a table of numbers (#270).

In the #235 practice round both such questions that passed the checks were
wrong: they swapped the table's columns, and the checks could not tell.
"""

from __future__ import annotations

import uuid

import pytest

from app.schemas.content import Difficulty, QuestionType
from app.services.extraction import (
    MOSTLY_NUMBERS_NOTE,
    ExtractedElement,
    Extraction,
    finish_material,
    looks_like_data_table,
)
from app.services.generation import is_numeric_answer, rejection_reasons
from app.services.grounding_evaluation import reason_kind
from app.services.material_seams import DraftQuestion
from app.services.retrieval import RetrievedChunk

# MIT 6.0002's springData.txt as the reader gives it: distance, then mass.
SPRING = (
    "Distance (m) Mass (kg) 0.0865 0.1 0.1015 0.15 0.1106 0.2 0.1279 0.25 0.1892 0.3 "
    "0.2695 0.35 0.2888 0.4 0.2425 0.45 0.3465 0.5 0.3225 0.55 0.3764 0.6 0.4263 0.65 "
    "0.4562 0.7 0.4502 0.75 0.4499 0.8 0.4534 0.85 0.4416 0.9 0.4304 0.95 0.437 1.0"
)
PROSE = (
    "Simulate 20 trials of 1000 spins each. Exp. return for Fair Roulette = 6.56%. "
    "Exp. return for European Roulette = -2.26%. Exp. return for American Roulette = "
    "-8.92%. As the number of spins grows, the expected return converges."
)


def chunk(text, page=1):
    return RetrievedChunk(uuid.uuid4(), 0, text, page, 0.1)


def mcq(prompt, options, correct, excerpt, page=1):
    return DraftQuestion(
        type=QuestionType.MCQ,
        difficulty=Difficulty.MEDIUM,
        prompt=prompt,
        options=options,
        correct_option=correct,
        source_slide=page,
        source_excerpt=excerpt,
    )


LOOKUP = "answer is a value looked up in a table of numbers, which the checks cannot confirm"


@pytest.mark.parametrize(
    ("prompt", "options", "correct"),
    [
        # The two questions the practice round passed; both are wrong.
        (
            "What is the mass corresponding to a Distance of 0.4 meters?",
            ("0.2888 kg", "0.2425 kg", "0.2695 kg", "0.3225 kg"),
            1,
        ),
        (
            "What is the mass corresponding to a Distance of 0.85 meters?",
            ("0.3465 kg", "0.3225 kg", "0.1892 kg", "0.4416 kg"),
            3,
        ),
    ],
)
def test_a_value_looked_up_in_a_table_of_numbers_is_rejected(prompt, options, correct):
    reasons = rejection_reasons(mcq(prompt, options, correct, SPRING[:120]), [chunk(SPRING)])
    assert LOOKUP in reasons


def test_a_number_from_lecture_prose_is_still_kept():
    draft = mcq(
        "What expected return did 1000 spins of European roulette give?",
        ("6.56%", "-2.26%", "-8.92%", "0.5%"),
        1,
        "Exp. return for European Roulette = -2.26%",
    )
    assert LOOKUP not in rejection_reasons(draft, [chunk(PROSE)])


def test_a_word_answer_about_a_table_is_still_kept():
    draft = mcq(
        "What does the first column of the spring data hold?",
        ("Distance", "Mass", "Force", "Time"),
        0,
        "Distance (m) Mass (kg)",
    )
    assert LOOKUP not in rejection_reasons(draft, [chunk(SPRING)])


def test_the_new_reason_has_its_own_kind():
    assert reason_kind(LOOKUP) == "table lookup: a number from a table of numbers"


@pytest.mark.parametrize(
    ("text", "data"),
    [
        (SPRING, True),
        (PROSE, False),
        ("x y 301.8 -10 206.5 -9 141.4 -8 181.5 -7 41.8 -6 36.7 -5", True),
        # Too short to judge.
        ("0.1 0.2 0.3", False),
        ("The three types of logistic regression are binary, multinomial and ordinal.", False),
    ],
)
def test_a_table_of_numbers_is_told_from_prose(text, data):
    assert looks_like_data_table(text) is data


@pytest.mark.parametrize(
    ("answer", "numeric"),
    [
        ("0.2425 kg", True),
        ("-28.0%", True),
        ("1e-3 m/s", True),
        ("42", True),
        ("Base layers", False),
        ("Three", False),
        ("0.5 is the threshold", False),
    ],
)
def test_a_numeric_answer_is_a_number_and_at_most_a_short_unit(answer, numeric):
    assert is_numeric_answer(answer) is numeric


def test_a_file_that_is_mostly_numbers_warns_the_lecturer():
    data = finish_material(
        Extraction([ExtractedElement("text", SPRING, 1)], "plain-text"), uuid.uuid4()
    )
    assert MOSTLY_NUMBERS_NOTE in data.warnings
    lecture = finish_material(
        Extraction([ExtractedElement("text", PROSE, 1)], "plain-text"), uuid.uuid4()
    )
    assert MOSTLY_NUMBERS_NOTE not in lecture.warnings
