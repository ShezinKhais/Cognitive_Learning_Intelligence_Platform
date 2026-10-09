"""Which topics a class found hard, from the comprehension labels of its
answers.

Owner: AI 1, Phase 5 (#55). The class comprehension alert looks at one
question as it closes; this looks at a whole topic across all its questions,
so a lecturer can see what to revisit. Plain functions over labelled answers,
so they need no model or database; DatabaseTopicAnswers reads the answers.

A topic's difficulty is the average of its answers' labels, weighted as the
classifier weighs key points: mastered 0, partial 0.5, struggling 1. So 0 is
a topic everyone understood and 1 one nobody did. A topic with too few
answers gets no level: two wrong answers are not a hard topic.

Free-text labels are estimates, so each topic also says how many of its
labels were uncertain. They still count in full; the count lets the lecturer
weigh them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable
from dataclasses import dataclass

from app.schemas.content import Difficulty
from app.schemas.session import ComprehensionLabel

LABEL_WEIGHT = {
    ComprehensionLabel.MASTERED.value: 0.0,
    ComprehensionLabel.PARTIAL.value: 0.5,
    ComprehensionLabel.STRUGGLING.value: 1.0,
}
# A score below EASY_BELOW is easy, from HARD_FROM up is hard, between is
# medium: three equal slices of 0 to 1.
EASY_BELOW = 0.33
HARD_FROM = 0.66
# Fewer answers than this and a topic is "not enough data", not easy or hard.
# Matches the class comprehension alert's minimum respondents.
MIN_ANSWERS = 5
# A label with less confidence than this is counted as uncertain. MCQ labels
# are 1.0; a free-text label falls below it when the model's marking and the
# answer's similarity to the reference disagree.
UNCERTAIN_BELOW = 0.6
NO_TOPIC = "No topic"


@dataclass(frozen=True)
class LabelledAnswer:
    """One student's labelled answer to one question."""

    student_id: Hashable
    question_id: Hashable
    topic: str | None
    label: str
    confidence: float
    # What the question generator guessed the question's difficulty to be.
    question_difficulty: str | None = None


@dataclass(frozen=True)
class TopicDifficulty:
    topic: str
    questions: int
    answers: int
    mastered: int
    partial: int
    struggling: int
    uncertain: int
    # None when the topic has fewer than MIN_ANSWERS answers.
    score: float | None
    level: Difficulty | None
    # The difficulty the generator gave most of the topic's questions, or
    # None when they are evenly split. Differs from `level` when the class
    # found a topic harder or easier than expected.
    expected: Difficulty | None


def level_for(score: float) -> Difficulty:
    if score < EASY_BELOW:
        return Difficulty.EASY
    if score >= HARD_FROM:
        return Difficulty.HARD
    return Difficulty.MEDIUM


def topic_key(topic: str | None) -> str:
    """The same topic however it is capitalised or spaced."""
    return " ".join((topic or "").split()).casefold()


def latest_answers(answers: Iterable[LabelledAnswer]) -> list[LabelledAnswer]:
    """One answer per student per question, keeping the last given.

    `answers` must be in the order they were labelled: a reclassified answer
    counts once, by its newest label, as in the class comprehension alert.
    """
    latest: dict[tuple[Hashable, Hashable], LabelledAnswer] = {}
    for answer in answers:
        latest[(answer.student_id, answer.question_id)] = answer
    return list(latest.values())


def _expected(answers: list[LabelledAnswer]) -> Difficulty | None:
    per_question = {a.question_id: a.question_difficulty for a in answers}
    guesses = Counter(
        d for d in per_question.values() if d in {level.value for level in Difficulty}
    ).most_common(2)
    if not guesses or (len(guesses) == 2 and guesses[0][1] == guesses[1][1]):
        return None
    return Difficulty(guesses[0][0])


def _summarise(name: str, answers: list[LabelledAnswer]) -> TopicDifficulty:
    counts = Counter(a.label for a in answers)
    score = (
        sum(LABEL_WEIGHT[a.label] for a in answers) / len(answers)
        if len(answers) >= MIN_ANSWERS
        else None
    )
    return TopicDifficulty(
        topic=name,
        questions=len({a.question_id for a in answers}),
        answers=len(answers),
        mastered=counts[ComprehensionLabel.MASTERED.value],
        partial=counts[ComprehensionLabel.PARTIAL.value],
        struggling=counts[ComprehensionLabel.STRUGGLING.value],
        uncertain=sum(a.confidence < UNCERTAIN_BELOW for a in answers),
        score=score,
        level=level_for(score) if score is not None else None,
        expected=_expected(answers),
    )


def topic_difficulty(answers: Iterable[LabelledAnswer]) -> list[TopicDifficulty]:
    """Every topic's difficulty, hardest first.

    Topics without enough answers for a level come last, most answered first.
    Labels that are not mastered, partial or struggling are not counted.
    """
    groups: dict[str, list[LabelledAnswer]] = {}
    names: dict[str, str] = {}
    for answer in latest_answers(answers):
        if answer.label not in LABEL_WEIGHT:
            continue
        key = topic_key(answer.topic)
        # A topic is shown as first spelt, with its spacing tidied.
        names.setdefault(key, " ".join((answer.topic or "").split()) or NO_TOPIC)
        groups.setdefault(key, []).append(answer)
    topics = [_summarise(names[key], group) for key, group in groups.items()]
    return sorted(
        topics,
        key=lambda t: (t.score is None, -(t.score or 0.0), -t.answers, t.topic.casefold()),
    )
