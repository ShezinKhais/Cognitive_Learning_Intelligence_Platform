from random import SystemRandom

import pytest
from pydantic import ValidationError as SchemaValidationError

from app.core.errors import ValidationError
from app.schemas.question_interaction import InteractionInput
from app.services.question_interaction import build_interaction


@pytest.mark.parametrize("kind", ["matching", "ordering"])
@pytest.mark.parametrize("permutation", [(0, 1), (1, 0)])
def test_two_item_shuffle_keeps_both_outcomes(kind, permutation, monkeypatch):
    def shuffle(_self, sequence):
        sequence[:] = permutation

    monkeypatch.setattr(SystemRandom, "shuffle", shuffle)
    labels = ["Term A", "Term B"] if kind == "matching" else []
    choices = ["First", "Second"]
    result = build_interaction(kind, InteractionInput(labels=labels, choices=choices))

    assert result.choices == [choices[index] for index in permutation]
    assert [result.choices[index] for index in result.correct_order] == choices


@pytest.mark.parametrize(
    "items",
    [
        {"choices": ["First", " first "]},
        {"labels": ["Label", " label "], "choices": ["One", "Two"]},
        {"choices": [str(index) for index in range(9)]},
    ],
)
def test_authoring_rejects_duplicates_and_too_many_choices(items):
    with pytest.raises(SchemaValidationError):
        InteractionInput(**items)


@pytest.mark.parametrize(
    ("labels", "choices", "message"),
    [
        (["One label"], ["A", "B"], "complete set"),
        (["Term | A", "Term B"], ["A", "B"], "pair separator"),
        (["Term A", "Term B"], ["A", "B | C"], "pair separator"),
    ],
)
def test_matching_authoring_requires_complete_pairs_without_separators(labels, choices, message):
    with pytest.raises(ValidationError, match=message):
        build_interaction("matching", InteractionInput(labels=labels, choices=choices))
