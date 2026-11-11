"""Retrieval across whole courses, and the tutor's abstention cutoff (#252).

No model involved: vectors are written by hand, two dimensions each.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.course_retrieval_evaluation import (
    AbstainScore,
    CourseQuery,
    Excerpt,
    Found,
    Result,
    abstain_score,
    best_cutoff,
    cosine_distance,
    load_query_set,
    rank_score,
    report,
    search,
    wilson,
)

QUERIES = Path(__file__).parent / "eval" / "retrieval_courses" / "queries.json"


def query(qid="q1", answers=(("a.pdf", 2),), split="dev", kinds=("text",), course="c"):
    return CourseQuery(qid, course, split, tuple(kinds), f"question {qid}", frozenset(answers))


def unanswerable(qid="u1", split="dev"):
    return query(qid, answers=(), split=split, kinds=("off-topic",))


def found(*items):
    """(material, page, distance) triples, nearest first."""
    return tuple(Found(m, p, d) for m, p, d in items)


def test_search_orders_a_whole_course_by_cosine_distance():
    excerpts = [
        Excerpt("a.pdf", 1, (0.0, 1.0)),
        Excerpt("b.pptx", 7, (1.0, 0.0)),
        Excerpt("a.pdf", 2, (1.0, 1.0)),
    ]
    ranked = search((1.0, 0.0), excerpts)
    assert [(f.material, f.page) for f in ranked] == [("b.pptx", 7), ("a.pdf", 2), ("a.pdf", 1)]
    assert ranked[0].distance == pytest.approx(0.0)
    assert ranked[1].distance == pytest.approx(1 - 1 / math.sqrt(2))
    assert cosine_distance((0.0, 0.0), (1.0, 0.0)) == 1.0


def test_a_result_knows_its_rank_precision_and_lecture():
    r = Result(
        query(answers=(("a.pdf", 2), ("a.pdf", 3))),
        found(("a.pdf", 9, 0.2), ("b.pdf", 2, 0.3), ("a.pdf", 3, 0.4), ("a.pdf", 2, 0.5)),
    )
    # Page 2 of b.pdf is not page 2 of a.pdf.
    assert r.rank == 3
    assert r.precision(k=4) == 0.5
    assert r.right_material_on_top
    assert r.top_distance == 0.2
    assert r.answered(0.2) and not r.answered(0.19)


def test_rank_scores_count_only_answerable_questions():
    results = [
        Result(query("q1"), found(("a.pdf", 2, 0.1))),
        Result(query("q2"), found(("a.pdf", 5, 0.1), ("a.pdf", 2, 0.2))),
        Result(query("q3"), found(("b.pdf", 2, 0.1))),
        Result(unanswerable(), found(("a.pdf", 2, 0.9))),
    ]
    s = rank_score(results, k=2)
    assert (s.questions, s.hit_at_1, s.hit_at_k, s.right_material) == (3, 1, 2, 2)
    assert s.mrr == pytest.approx((1 + 0.5 + 0) / 3)
    with pytest.raises(ValueError):
        rank_score([Result(unanswerable(), found(("a.pdf", 1, 0.5)))])


def test_abstention_counts_both_ways_of_being_wrong():
    results = [
        Result(query("q1"), found(("a.pdf", 2, 0.30))),
        Result(query("q2"), found(("a.pdf", 2, 0.70))),  # wrongly abstained at 0.65
        Result(unanswerable("u1"), found(("a.pdf", 1, 0.80))),  # abstains
        Result(unanswerable("u2"), found(("a.pdf", 1, 0.50))),  # answers: wrong
    ]
    s = abstain_score(results, 0.65)
    assert (s.unanswerable, s.abstained, s.answerable, s.wrongly_abstained) == (2, 1, 2, 1)
    assert s.balanced_accuracy == pytest.approx(0.5)
    assert AbstainScore(0.5, 0, 0, 0, 0).balanced_accuracy == 0.0


def test_the_best_cutoff_separates_answerable_from_unanswerable():
    results = [
        Result(query("q1"), found(("a.pdf", 2, 0.30))),
        Result(query("q2"), found(("a.pdf", 2, 0.42))),
        Result(unanswerable("u1"), found(("a.pdf", 1, 0.55))),
        Result(unanswerable("u2"), found(("a.pdf", 1, 0.61))),
    ]
    cutoff = best_cutoff(results)
    # Anything between 0.42 and 0.55 is perfect; the largest gap midpoint wins.
    assert 0.42 <= cutoff < 0.55
    assert abstain_score(results, cutoff).balanced_accuracy == 1.0


def test_of_equally_good_cutoffs_the_one_answering_more_is_taken():
    results = [
        Result(query("q1"), found(("a.pdf", 2, 0.30))),
        Result(unanswerable("u1"), found(("a.pdf", 1, 0.50))),
        Result(query("q2"), found(("a.pdf", 2, 0.60))),
        Result(unanswerable("u2"), found(("a.pdf", 1, 0.80))),
    ]
    # At 0.40, q2 is refused and both off-topic questions are too: 0.75.
    # At 0.70, q2 is answered but so is u1: also 0.75. The larger is taken,
    # since a student notices a refused question more than a thin answer.
    assert abstain_score(results, 0.40).balanced_accuracy == pytest.approx(0.75)
    assert abstain_score(results, 0.70).balanced_accuracy == pytest.approx(0.75)
    assert best_cutoff(results) == 0.7


def test_wilson_leaves_room_at_the_edges():
    low, high = wilson(10, 10)
    assert 0.65 < low < 0.75 and high == 1.0
    low, high = wilson(0, 6)
    assert low == 0.0 and 0.35 < high < 0.45


def write(tmp_path, data):
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(data))
    return path


def base(**query):
    item = {
        "id": "q1",
        "course": "stats",
        "split": "dev",
        "kinds": ["text"],
        "query": "What is a p-value?",
        "answers": [{"material": "a.pdf", "pages": [3, 4]}],
    }
    item.update(query)
    return {"courses": {"stats": ["a.pdf", "b.pdf"]}, "queries": [item]}


def test_a_question_set_loads(tmp_path):
    courses, queries = load_query_set(write(tmp_path, base()))
    assert courses == {"stats": ["a.pdf", "b.pdf"]}
    assert queries[0].answers == frozenset({("a.pdf", 3), ("a.pdf", 4)})
    assert queries[0].answerable


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"course": "physics"}, "no course"),
        ({"split": "test"}, "split"),
        ({"kinds": ["pictures"]}, "kinds"),
        ({"kinds": []}, "kinds"),
        ({"answers": [{"material": "z.pdf", "pages": [1]}]}, "not one of"),
        ({"answers": [{"material": "a.pdf", "pages": []}]}, "at least one page"),
        ({"answers": []}, "exactly when"),
        ({"kinds": ["off-topic"]}, "exactly when"),
    ],
)
def test_a_mistake_in_the_question_set_is_named(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        load_query_set(write(tmp_path, base(**change)))


def test_an_id_used_twice_is_refused(tmp_path):
    data = base()
    data["queries"].append(dict(data["queries"][0]))
    with pytest.raises(ValueError, match="twice"):
        load_query_set(write(tmp_path, data))


def test_the_committed_question_set_is_valid_and_balanced():
    courses, queries = load_query_set(QUERIES)
    assert len(courses) == 5
    assert len(queries) >= 100
    for split in ("dev", "heldout"):
        members = [q for q in queries if q.split == split]
        assert any(q.answerable for q in members)
        assert any(not q.answerable for q in members)
    kinds = {k for q in queries for k in q.kinds}
    assert {"diagram", "table", "formula", "image-only", "arabic", "student-wording"} <= kinds


def test_the_report_scores_by_kind_and_chooses_a_cutoff_on_dev_only():
    results = [
        Result(query("d1", kinds=("diagram",)), found(("a.pdf", 2, 0.30))),
        Result(query("d2"), found(("a.pdf", 9, 0.40), ("a.pdf", 2, 0.45))),
        Result(unanswerable("du1"), found(("a.pdf", 1, 0.60))),
        Result(query("h1", split="heldout"), found(("a.pdf", 2, 0.35))),
        Result(unanswerable("hu1", split="heldout"), found(("a.pdf", 1, 0.50))),
    ]
    text = report(results, header=["# Test"], current_cutoff=0.65, k=2)
    assert "| diagram: answered by a diagram | 1 | 1 of 1" in text
    assert "| split: heldout | 1 |" in text
    # On dev, 0.5 separates 0.40 from 0.60; held-out is scored with it.
    assert "cutoff chosen on the dev questions is **0.50**" in text
    assert "| **held-out, cutoff chosen on dev** | 0.50 | 0 of 1" in text
    assert "| **held-out, current setting** | 0.65 | 0 of 1" in text
    assert "| d2 | dev | text | question d2 | a.pdf p.2 | 2 | a.pdf p.9, 0.400 |" in text
    assert "| du1 | dev | off-topic | question du1 | nothing | - |" in text


def test_without_held_out_questions_no_cutoff_is_chosen():
    results = [
        Result(query("d1"), found(("a.pdf", 2, 0.30))),
        Result(unanswerable("du1"), found(("a.pdf", 1, 0.60))),
    ]
    assert "No cutoff is chosen" in report(results, header=["# Test"])
