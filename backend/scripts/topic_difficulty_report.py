"""Compares topic difficulty from the human labels with topic difficulty from
the classifier's, using a results file the evaluation already wrote.

Not a test, and needs no model: run evaluate_classifier with --out first,
then from backend/:

    python -m scripts.topic_difficulty_report tests/eval/results.csv

Each eval question is its own topic. A classifier that ranks topics like the
human does is useful to a lecturer even where it gets single answers wrong.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.services.topic_difficulty import LabelledAnswer, TopicDifficulty, topic_difficulty

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"


def _by_topic(rows: list[dict[str, str]], column: str, topics: dict[str, str]):
    answers = [
        LabelledAnswer(
            student_id=row["answer_id"],
            question_id=row["question_id"],
            topic=topics[row["question_id"]],
            label=row[column],
            confidence=float(row["confidence"] or 1.0) if column == "predicted" else 1.0,
        )
        for row in rows
    ]
    return {t.topic: t for t in topic_difficulty(answers)}


def _cell(topic: TopicDifficulty | None) -> str:
    if topic is None or topic.score is None:
        return "not enough data"
    return f"{topic.score:.2f} {topic.level.value}"


def main(results: Path) -> None:
    questions = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    topics = {q["question_id"]: q["topic"] for q in questions}
    with (EVAL_DIR / "answers_to_label.csv").open(newline="", encoding="utf-8") as f:
        question_of = {row["answer_id"]: row["question_id"] for row in csv.DictReader(f)}
    with results.open(newline="", encoding="utf-8") as f:
        rows = [{**row, "question_id": question_of[row["answer_id"]]} for row in csv.DictReader(f)]

    # An unreadable reply has no prediction, so it is left out of both sides.
    marked = [row for row in rows if row["predicted"] != "error"]
    human = _by_topic(marked, "human", topics)
    predicted = _by_topic(marked, "predicted", topics)

    print(f"{'topic':<40} {'answers':>7}  {'human':<16} {'classifier':<16} uncertain")
    agree = 0
    for name, topic in human.items():
        mine = predicted.get(name)
        agree += mine is not None and mine.level == topic.level
        print(
            f"{name:<40} {topic.answers:>7}  {_cell(topic):<16} {_cell(mine):<16} "
            f"{mine.uncertain if mine else 0}"
        )
    print(f"\nlevels agree on {agree} of {len(human)} topics")
    print("human ranking      " + " > ".join(human))
    print("classifier ranking " + " > ".join(predicted))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, help="a CSV written by evaluate_classifier --out")
    main(parser.parse_args().results)
