"""A written summary of how a class did, for its lecturer.

Owner: AI 1, Phase 7 (#67). The deliverable is "AI summaries generated from
verified database values", so the model writes and the code checks:

1. The facts are worked out by code, from topic_difficulty's results, which
   are read from stored comprehension labels. The model never counts.
2. The model turns those facts into a few sentences.
3. Every topic and number in its sentences must match the facts. A summary
   that does not is asked for once more, then replaced by the facts as plain
   text, so the lecturer always gets something true.

Only topics with enough answers for a level are given to the model: a topic
with too few has no level to report, and leaving it out stops the model
calling it easy or hard on a handful of answers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas.content import Difficulty
from app.services.topic_difficulty import TopicDifficulty


@dataclass(frozen=True)
class TopicFact:
    """What the model may say about one topic. Every field is checked
    against the summary it writes."""

    topic: str
    level: Difficulty
    answers: int
    mastered: int
    partial: int
    struggling: int
    uncertain: int
    # The generator's guess at the topic's difficulty, only when the class
    # found it different: a match tells the lecturer nothing new.
    expected: Difficulty | None


def lecturer_facts(topics: Iterable[TopicDifficulty]) -> list[TopicFact]:
    """The facts behind a lecturer's summary, hardest topic first.

    `topics` keeps the order topic_difficulty returns, hardest first. Topics
    without a level are left out (see the module docstring); the score is left
    out because the level already says it in words, and a second number is one
    more the model could get wrong.
    """
    return [
        TopicFact(
            topic=t.topic,
            level=t.level,
            answers=t.answers,
            mastered=t.mastered,
            partial=t.partial,
            struggling=t.struggling,
            uncertain=t.uncertain,
            expected=t.expected if t.expected != t.level else None,
        )
        for t in topics
        if t.level is not None
    ]


def fact_line(fact: TopicFact) -> str:
    """One fact as the model reads it, and as the fallback summary shows it."""
    line = (
        f"{fact.topic}: {fact.level.value}. {fact.answers} answers: "
        f"{fact.mastered} mastered, {fact.partial} partial, {fact.struggling} struggling."
    )
    if fact.uncertain:
        label = "label" if fact.uncertain == 1 else "labels"
        line += f" {fact.uncertain} uncertain {label}."
    if fact.expected is not None:
        line += f" Expected {fact.expected.value}."
    return line
