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
    confidence_buckets,
    confidence_separation,
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


def test_confidence_buckets_count_right_labels_at_each_level():
    low, middle, high = confidence_buckets(
        [0.3, 0.5, 0.6, 0.84, 0.85, 0.95], [True, False, False, False, True, True]
    )

    assert (low.low, low.high, low.answers, low.right, low.accuracy) == (0.0, 0.6, 2, 1, 0.5)
    assert (middle.answers, middle.accuracy) == (2, 0.0)
    assert (high.low, high.high, high.answers, high.accuracy) == (0.85, None, 2, 1.0)


def test_an_empty_bucket_has_no_accuracy():
    [low, high] = confidence_buckets([0.9], [True], edges=(0.5,))

    assert (low.answers, low.accuracy) == (0, None)
    assert high.answers == 1


def test_separation_is_one_when_right_labels_are_always_more_confident():
    assert confidence_separation([0.9, 0.8, 0.4, 0.3], [True, True, False, False]) == 1.0
    assert confidence_separation([0.3, 0.9], [True, False]) == 0.0


def test_separation_is_a_coin_flip_when_confidence_is_the_same():
    assert confidence_separation([0.7, 0.7], [True, False]) == 0.5


def test_separation_needs_both_right_and_wrong_labels():
    assert confidence_separation([0.9, 0.4], [True, True]) is None


def test_confidences_and_results_must_pair_up():
    with pytest.raises(ValueError):
        confidence_buckets([0.9], [True, False])
    with pytest.raises(ValueError):
        confidence_separation([0.9, 0.4], [True])


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
