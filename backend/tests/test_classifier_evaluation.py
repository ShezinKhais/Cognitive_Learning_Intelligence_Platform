"""The agreement measures behind the accuracy baseline, and the labelled set
they are run on."""

import csv
import json
from pathlib import Path

import pytest

from app.services.classifier_evaluation import (
    LABELS,
    accuracy,
    cohen_kappa,
    confusion_matrix,
    label_stats,
    macro_f1,
)

EVAL_DIR = Path(__file__).parent / "eval"


def test_accuracy_is_the_share_that_match():
    assert (
        accuracy(
            ["mastered", "partial", "struggling", "partial"],
            ["mastered", "partial", "partial", "struggling"],
        )
        == 0.5
    )


def test_the_confusion_matrix_counts_each_pair():
    matrix = confusion_matrix(
        ["mastered", "partial", "partial"], ["mastered", "struggling", "partial"]
    )

    assert matrix["partial"] == {"mastered": 0, "partial": 1, "struggling": 1}
    assert matrix["mastered"]["mastered"] == 1


def test_precision_and_recall_per_label():
    stats = {
        s.label: s
        for s in label_stats(
            ["mastered", "mastered", "struggling"], ["mastered", "struggling", "struggling"]
        )
    }

    assert stats["mastered"].precision == 1.0
    assert stats["mastered"].recall == 0.5
    assert stats["struggling"].precision == 0.5
    assert stats["partial"].support == 0 and stats["partial"].recall is None


def test_macro_f1_is_one_when_everything_matches():
    labels = ["mastered", "partial", "struggling"]
    assert macro_f1(labels, labels) == 1.0


def test_kappa_is_one_for_identical_labels_and_zero_for_chance():
    same = ["mastered", "partial", "struggling", "partial"]
    assert cohen_kappa(same, same) == 1.0
    # Every pair disagrees in a way chance would predict half the time.
    assert cohen_kappa(
        ["mastered", "struggling"] * 2, ["mastered", "mastered", "struggling", "struggling"]
    ) == pytest.approx(0.0)


def test_mismatched_lengths_are_refused():
    with pytest.raises(ValueError):
        accuracy(["mastered"], ["mastered", "partial"])


def test_every_labelled_answer_belongs_to_a_question_with_a_checklist():
    questions = {q["question_id"]: q for q in json.loads((EVAL_DIR / "questions.json").read_text())}
    with (EVAL_DIR / "answers_to_label.csv").open(newline="") as f:
        answers = list(csv.DictReader(f))

    assert len(answers) == 40
    for answer in answers:
        question = questions[answer["question_id"]]
        assert 2 <= len(question["key_points"]) <= 4
        assert answer["label_luna"] in LABELS
        assert answer["label_nour"] in ("", *LABELS)
