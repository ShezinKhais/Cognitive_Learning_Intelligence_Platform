"""How often the session summaries pass their checks, for the AI evaluation
report (Phase 8, AI 1, #73).

Not a test. Needs Ollama with the chat model from .env. Run from backend/:

    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_summaries
    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_summaries --out tests/eval/SUMMARIES.md

The class is the labelled answer set in tests/eval: 40 answers to 5
questions, each with its agreed label, read as 8 students who each answered
all 5 (the n-th answer to every question is student n's). The lecturer
summary is written --rounds times and each student's summary --student-rounds
times. The model writes a sentence per topic, and each is the model's only
if it agrees with that topic's facts (app/services/session_summary.py); the
topics whose sentences fail are asked for once more, with their problems
listed, and a sentence still wrong is replaced by that topic's plain facts.
This counts how each summary ended, and what share of all sentences were the
model's, and keeps a few summaries for a person to read.
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
from app.services.session_summary import (
    MAX_SENTENCES,
    STUDENT_PROMPT_VERSION,
    SUMMARY_PROMPT_VERSION,
    LecturerSummariser,
    StudentSummariser,
    lecturer_facts,
    student_facts,
)
from app.services.topic_difficulty import LabelledAnswer, topic_difficulty

EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"
OUTCOMES = ("first try", "after one retry", "partly plain facts", "plain facts")


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
    # "Topic: problem", from a topic's sentence: the problem alone.
    problem = problem.split(": ", 1)[-1] if ": " in problem else problem
    return re.sub(r"\b\d+(?:\.\d+)?\b", "N", problem.split(":")[0])


def quoted(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def outcome(summary, calls: int) -> str:
    if summary.source == "facts":
        return "plain facts"
    if summary.source == "mixed":
        return "partly plain facts"
    return "first try" if calls == 1 else "after one retry"


def model_sentences(summary, topics: int) -> int:
    """How many of the summary's topic sentences are the model's."""
    if summary.source == "facts":
        return 0
    failed = {p.split(": ")[0] for p in summary.problems}
    return topics - len(failed)


async def main(rounds: int, student_rounds: int) -> str:
    settings = get_settings()
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    answers = class_answers()
    students = sorted({a.student_id for a in answers})
    print(f"model {settings.ollama_model}, {len(students)} students, {len(answers)} answers\n")

    tallies = {"Lecturer": Counter(), "Student": Counter()}
    sentences = {"Lecturer": Counter(), "Student": Counter()}
    lecturer_topics = len(lecturer_facts(topic_difficulty(answers))[:MAX_SENTENCES])
    problems: Counter = Counter()
    examples: list[str] = []

    for n in range(rounds):
        chat = CountingChat(client)
        summary = await LecturerSummariser(chat, settings.ollama_model).summarise(
            topic_difficulty(answers)
        )
        result = outcome(summary, chat.calls)
        tallies["Lecturer"][result] += 1
        sentences["Lecturer"]["all"] += lecturer_topics
        sentences["Lecturer"]["model"] += model_sentences(summary, lecturer_topics)
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
            topics = len(student_facts(answers, student))
            sentences["Student"]["all"] += topics
            sentences["Student"]["model"] += model_sentences(summary, topics)
            problems.update(problem_kind(p) for p in summary.problems)
            print(f"{student}, round {n + 1}: {result}")
            if n == 0 and student in students[:2]:
                examples.append(f"{student.capitalize()} ({result}):\n\n{quoted(summary.text)}")

    table = [
        "| Summary | Written | "
        + " | ".join(o.capitalize() for o in OUTCOMES)
        + " | Sentences that are the model's |",
        "|---|---|" + "---|" * (len(OUTCOMES) + 1),
    ]
    for who, tally in tallies.items():
        total = sum(tally.values())
        cells = [f"{tally[o]} ({tally[o] / total:.0%})" if total else "0" for o in OUTCOMES]
        made, of = sentences[who]["model"], sentences[who]["all"]
        share = f"{made} of {of} ({made / of:.0%})" if of else "0"
        table.append(f"| {who} | {total} | " + " | ".join(cells) + f" | {share} |")
    failures = ["| Problem in the final failed attempt | Summaries |", "|---|---|"] + [
        f"| {kind} | {count} |" for kind, count in problems.most_common()
    ]
    report = "\n".join(table)
    if problems:
        report += "\n\n" + "\n".join(failures)
    print("\n" + report)
    return (
        f"# Session summaries\n\nModel `{settings.ollama_model}`, prompts "
        f"`{SUMMARY_PROMPT_VERSION}` and `{STUDENT_PROMPT_VERSION}`, on the labelled answer "
        f"set read as {len(students)} students. Each summary ends as the model's on its first "
        "try, the model's after one retry for the topics that failed, partly plain facts (a "
        "topic's sentence still wrong after the retry shows that topic's facts), or all "
        "plain facts.\n\n" + report + "\n\n## Examples\n\n" + "\n\n".join(examples) + "\n"
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
