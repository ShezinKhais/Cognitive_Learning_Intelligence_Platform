"""Bootstrap confidence intervals for the AI evaluation report (Phase 8, AI 1, #73)."""

import pytest

from app.services.confidence_intervals import Interval, bootstrap, markdown_table, mean, proportion
from scripts.confidence_intervals import grounding_counts, hit, reciprocal, retrieval_ranks


def test_the_value_is_the_statistic_on_the_items_themselves():
    interval = proportion(9, 25)
    assert interval.value == pytest.approx(0.36)
    assert interval.n == 25


def test_the_interval_holds_the_value_and_stays_in_range():
    interval = proportion(6, 9)
    assert 0.0 <= interval.low <= interval.value <= interval.high <= 1.0


def test_identical_items_give_no_uncertainty():
    interval = bootstrap([1.0] * 20, mean)
    assert (interval.low, interval.value, interval.high) == (1.0, 1.0, 1.0)


def test_more_items_give_a_narrower_interval():
    small, large = proportion(6, 9), proportion(60, 90)
    assert large.high - large.low < small.high - small.low


def test_a_fixed_seed_gives_the_same_interval_every_time():
    assert proportion(9, 25) == proportion(9, 25)


def test_no_items_is_an_error():
    with pytest.raises(ValueError):
        bootstrap([], mean)


def test_the_table_prints_shares_and_scores():
    table = markdown_table(
        [
            ("Share", Interval(0.36, 0.2, 0.56, 25), "%"),
            ("Score", Interval(0.7, 0.5, 0.9, 11), "2dp"),
        ]
    )
    assert "| Share | 36% | 20% to 56% | 25 |" in table
    assert "| Score | 0.70 | 0.50 to 0.90 | 11 |" in table


def test_ranks_are_read_from_the_retrieval_results(tmp_path):
    results = tmp_path / "RETRIEVAL_RESULTS.md"
    results.write_text(
        "| Kind | Question | Answer on | Before: rank (top page) | After: rank (top page) |\n"
        "|---|---|---|---|---|\n"
        "| image | A picture question | 9 | - (8) | 6 (8) |\n"
        "| text | A text question | 5 | 1 (5) | 1 (5) |\n"
    )
    assert retrieval_ranks(results) == [(None, 6), (1, 1)]


def test_hit_and_reciprocal_rank():
    assert (hit(5), hit(6), hit(None)) == (1.0, 0.0, 0.0)
    assert (reciprocal(2), reciprocal(None)) == (0.5, 0.0)


def test_grounding_counts_are_read_from_the_summary(tmp_path):
    summary = tmp_path / "GROUNDING_RESULTS.md"
    summary.write_text("| Drafts | 25 |\n| Accepted | 9 |\n")
    assert grounding_counts(summary) == (9, 25)
