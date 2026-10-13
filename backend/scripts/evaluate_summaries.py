"""How often the session summaries pass their checks, for the AI evaluation
report (Phase 8, AI 1, #73).

Not a test. Needs Ollama with the chat model from .env. Run from backend/:

    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_summaries
    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_summaries --out tests/eval/SUMMARIES.md

The class is the labelled answer set in tests/eval: 40 answers to 5
questions, each with its agreed label, read as 8 students who each answered
all 5 (the n-th answer to every question is student n's). The lecturer
summary is written --rounds times and each student's summary --student-rounds
times. Every summary is the model's only if every sentence agrees with the
facts (app/services/session_summary.py); a failed one is retried once with
its problems listed, then replaced by the plain facts. This counts which of
the three each summary ended as, and keeps a few for a person to read.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from collections import Counter
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.session_summary import LecturerSummariser, StudentSummariser
from app.services.topic_difficulty import LabelledAnswer, topic_difficulty

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
OUTCOMES = ("first try", "after one retry", "plain facts")


class CountingChat:
    """The chat client, counting the calls one summary makes."""

    def __init__(self, client) -> None:
        self._client = client
        self.calls = 0
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls += 1
        return await self._client.chat.completions.create(**kwargs)


def class_answers() -> list[LabelledAnswer]:
    questions = {
        q["question_id"]: q
        for q in json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    }
    with (EVAL_DIR / "answers_to_label.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    seen: Counter = Counter()
    answers = []
    for row in rows:
        question = questions[row["question_id"]]
        seen[row["question_id"]] += 1
        answers.append(
            LabelledAnswer(
                student_id=f"student {seen[row['question_id']]}",
                question_id=row["question_id"],
                topic=question["topic"],
                label=row["label_final"],
                confidence=0.8,
                source_slide=question.get("source_slide"),
            )
        )
    return answers


def problem_kind(problem: str) -> str:
    """A check's finding without its numbers and topic names, to count alike."""
    if problem.startswith("does not mention the hardest"):
        return "leaves out the hardest topic"
    if problem.startswith("does not mention"):
        return "leaves out a topic"
    return re.sub(r"\b\d+(?:\.\d+)?\b", "N", problem.split(":")[0])


def quoted(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def outcome(summary, calls: int) -> str:
    if summary.source != "model":
        return "plain facts"
    return "first try" if calls == 1 else "after one retry"


async def main(rounds: int, student_rounds: int) -> str:
    settings = get_settings()
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    answers = class_answers()
    students = sorted({a.student_id for a in answers})
    print(f"model {settings.ollama_model}, {len(students)} students, {len(answers)} answers\n")

    tallies = {"Lecturer": Counter(), "Student": Counter()}
    problems: Counter = Counter()
    examples: list[str] = []

    for n in range(rounds):
        chat = CountingChat(client)
        summary = await LecturerSummariser(chat, settings.ollama_model).summarise(
            topic_difficulty(answers)
        )
        result = outcome(summary, chat.calls)
        tallies["Lecturer"][result] += 1
        problems.update(problem_kind(p) for p in summary.problems)
        print(f"lecturer {n + 1}: {result}")
        if n == 0:
            examples.append(f"Lecturer ({result}):\n\n{quoted(summary.text)}")

    for n in range(student_rounds):
        for student in students:
            chat = CountingChat(client)
            summary = await StudentSummariser(chat, settings.ollama_model).summarise(
                answers, student
            )
            result = outcome(summary, chat.calls)
            tallies["Student"][result] += 1
            problems.update(problem_kind(p) for p in summary.problems)
            print(f"{student}, round {n + 1}: {result}")
            if n == 0 and student in students[:2]:
                examples.append(f"{student.capitalize()} ({result}):\n\n{quoted(summary.text)}")

    table = [
        "| Summary | Written | " + " | ".join(o.capitalize() for o in OUTCOMES) + " |",
        "|---|---|" + "---|" * len(OUTCOMES),
    ]
    for who, tally in tallies.items():
        total = sum(tally.values())
        cells = [f"{tally[o]} ({tally[o] / total:.0%})" if total else "0" for o in OUTCOMES]
        table.append(f"| {who} | {total} | " + " | ".join(cells) + " |")
    failures = ["| Problem in the final failed attempt | Summaries |", "|---|---|"] + [
        f"| {kind} | {count} |" for kind, count in problems.most_common()
    ]
    report = "\n".join(table)
    if problems:
        report += "\n\n" + "\n".join(failures)
    print("\n" + report)
    return (
        f"# Session summaries\n\nModel `{settings.ollama_model}`, prompts "
        "`lecturer-summary-v3` and `student-summary-v3`, on the labelled answer set read "
        f"as {len(students)} students. Each summary ends as the model's on its first try, "
        "the model's after one retry with its problems listed, or the plain facts.\n\n"
        + report
        + "\n\n## Examples\n\n"
        + "\n\n".join(examples)
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=10, help="lecturer summaries to write")
    parser.add_argument("--student-rounds", type=int, default=2, help="summaries per student")
    parser.add_argument("--out", type=Path, help="also write the results as Markdown")
    args = parser.parse_args()
    markdown = asyncio.run(main(args.rounds, args.student_rounds))
    if args.out:
        args.out.write_text(markdown)
        print(f"\nwritten to {args.out}")
