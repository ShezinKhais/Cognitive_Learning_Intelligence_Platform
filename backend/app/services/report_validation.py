"""Responsible-AI and privacy checks for what a report says about a student.

Owner: Cyber 1, Phase 7. Pure functions: no database, no model. They check text
and summaries that other code produced, so the same rules apply whether a
sentence was written by a template (student_report.py), by a model (AI 1's
session summaries) or by anyone else.

The rules, each one a way a report could wrong a student:

* Engagement and comprehension are separate measures. No text or field may merge
  them into one verdict, and engagement may never be the reason for an action
  item: a camera or a click rate says nothing about whether someone understood.
* A report describes what was observed, not the person. No labels about
  character, motivation or ability ("lazy", "unmotivated", "weak student").
* A student's report is about that student. It never names or compares with
  another student, or "the class".
* Raw readings (gaze, face, voice) and accommodations never appear. The report
  may say how many signals backed an engagement figure; not what they read.
* Text that carries an instruction aimed at a model, markup or a disguised word
  is not shown (text_screening).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas.session import (
    ActionItem,
    ComprehensionLabel,
    EngagementStatus,
    StudentSessionSummary,
)
from app.services.text_screening import (
    contains_markup,
    has_mixed_script_word,
    looks_like_instruction,
    strip_unsafe_characters,
)

MAX_ACTION_ITEMS = 5
MAX_ACTION_TEXT_LENGTH = 240
ACTION_KINDS = ("revisit_topic", "review_missed")

_LABELLING = re.compile(
    r"\b(lazy|unmotivated|unmotivation|stupid|dumb|slow learner|weak student|poor student|"
    r"hopeless|incapable|disinterested|careless|bad student|failing student|problem student|"
    r"cheat\w*|dishonest)\b",
    flags=re.IGNORECASE,
)
_COMPARISON = re.compile(
    r"\b(the class|classmates?|other students?|everyone else|peers|the rest of|"
    r"compared (?:to|with) (?:others|the class)|than (?:most|other)|top of|bottom of|ranked)\b",
    flags=re.IGNORECASE,
)
_RAW_SIGNALS = re.compile(
    r"\b(gaze|face[_ ]?present\w*|looking away|looked away|eyes?|camera|webcam|"
    r"microphone|speaking|voice)\b",
    flags=re.IGNORECASE,
)
_ACCOMMODATION = re.compile(
    r"\b(accommodat\w*|accessib\w*|disabilit\w*|impair\w*|dyslex\w*|adhd|autis\w*|"
    r"special needs)\b",
    flags=re.IGNORECASE,
)
_MERGED = re.compile(
    r"\b(overall (?:score|rating|performance)|combined (?:score|rating)|"
    r"engagement and (?:comprehension|understanding) (?:score|combined|together)|"
    r"engagement[- ]adjusted|total (?:score|rating))\b",
    flags=re.IGNORECASE,
)
# Phrases that turn an engagement reading into a claim about understanding or
# the other way round.
_CROSSED = re.compile(
    r"(?:(?:disengaged|not engaged|low engagement)[^.]{0,60}"
    r"(?:so|therefore|which means|means)[^.]{0,40}(?:understand|comprehen|learn|grasp))"
    r"|(?:(?:struggl|misunderstood|did not understand)[^.]{0,60}"
    r"(?:so|therefore|which means|because)[^.]{0,40}(?:disengag|not paying|inattentive))",
    flags=re.IGNORECASE,
)


def text_problems(text: str, *, other_names: Iterable[str] = ()) -> list[str]:
    """Why a sentence about a student must not be shown, or an empty list."""
    problems: list[str] = []
    cleaned = strip_unsafe_characters(text or "")
    if not cleaned.strip():
        return ["the text is empty"]
    if cleaned != (text or "").strip():
        problems.append("the text has control characters")
    if looks_like_instruction(cleaned):
        problems.append("the text carries an instruction aimed at a model")
    if contains_markup(cleaned):
        problems.append("the text contains markup or a link")
    if has_mixed_script_word(cleaned):
        problems.append("the text has a word in mixed alphabets")
    if _LABELLING.search(cleaned):
        problems.append("the text labels the student rather than describing what was seen")
    if _COMPARISON.search(cleaned):
        problems.append("the text compares the student with others")
    if _RAW_SIGNALS.search(cleaned):
        problems.append("the text reports a raw camera or voice reading")
    if _ACCOMMODATION.search(cleaned):
        problems.append("the text mentions an accommodation or health matter")
    if _MERGED.search(cleaned):
        problems.append("the text merges engagement and comprehension into one figure")
    if _CROSSED.search(cleaned):
        problems.append("the text infers understanding from engagement, or the reverse")
    lowered = cleaned.casefold()
    for name in other_names:
        name = (name or "").strip()
        if len(name) >= 3 and name.casefold() in lowered:
            problems.append("the text names another student")
            break
    return problems


def topic_name_problems(topic: str) -> list[str]:
    """Why a topic name must not be shown. A lecture may be about a camera, a
    voice or a gaze, so a name is held only to the rules about attacks."""
    cleaned = strip_unsafe_characters(topic or "")
    problems = []
    if not cleaned.strip():
        problems.append("the topic name is empty")
    if cleaned != (topic or "").strip():
        problems.append("the topic name has control characters")
    if looks_like_instruction(cleaned):
        problems.append("the topic name carries an instruction aimed at a model")
    if contains_markup(cleaned) or has_mixed_script_word(cleaned):
        problems.append("the topic name has markup or a mixed-alphabet word")
    return problems


def action_item_problems(item: ActionItem) -> list[str]:
    """The topic named in an item is checked as a topic name; the words the
    report wrote around it are checked as report text."""
    problems = []
    wording = item.text
    if item.topic:
        problems += topic_name_problems(item.topic)
        wording = wording.replace(item.topic, "")
    if item.kind not in ACTION_KINDS:
        problems.append(f"action kind {item.kind!r} is not one a report may suggest")
    if len(item.text) > MAX_ACTION_TEXT_LENGTH:
        problems.append("the action item is too long")
    problems += text_problems(wording)
    return problems


def summary_problems(
    summary: StudentSessionSummary, *, session_id: object, student_id: object
) -> list[str]:
    """Everything wrong with a student's summary, or an empty list."""
    problems: list[str] = []
    if summary.student_id != student_id or summary.engagement.student_id != student_id:
        problems.append("the summary is about a different student")
    if summary.session_id != session_id or summary.engagement.session_id != session_id:
        problems.append("the summary is about a different session")
    if summary.questions_attempted < 0 or summary.questions_missed < 0:
        problems.append("a question count is negative")
    for topic, label in summary.comprehension_by_topic.items():
        if label not in set(ComprehensionLabel):
            problems.append("a comprehension label is not a known label")
        problems += topic_name_problems(topic)

    engagement = summary.engagement
    if engagement.status is EngagementStatus.INSUFFICIENT_DATA:
        if engagement.score is not None:
            problems.append("an engagement score is given without enough data")
    elif engagement.score is None:
        problems.append("an engagement status is given without a score")
    if engagement.confidence == 0.0 and engagement.status is not EngagementStatus.INSUFFICIENT_DATA:
        problems.append("an engagement status is given with no confidence")
    if engagement.status is EngagementStatus.DISENGAGED and len(engagement.signals_available) < 2:
        problems.append("disengaged is claimed on fewer than two signals")

    if len(summary.action_items) > MAX_ACTION_ITEMS:
        problems.append("too many action items")
    for item in summary.action_items:
        problems += [f"action item: {p}" for p in action_item_problems(item)]
    return problems
