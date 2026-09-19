"""Answer scoring for live checkpoints.

Owner: AI 1, Phase 3. MCQ scoring is immediate and deterministic: compare the
selected index against the question's answer key. Free-text answers are
stored (app.repositories.response_repository) but not scored here -- Phase 5
adds the Mastered/Partial/Struggling classifier described in PHASES.md, and
`classify_free_text` is the seam it plugs into, same pattern as
app.services.material_seams' Protocols for a not-yet-built workstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.question import Question


@dataclass(frozen=True)
class ScoredAnswer:
    """The outcome of scoring one submission.

    `correct` is None for free text: FeedbackResultPayload documents that as
    "classifying", not "wrong", and nothing here should claim more certainty
    than a classifier that does not exist yet.
    """

    correct: bool | None
    explanation: str | None
    source_slide: int | None


def score_mcq(question: Question, selected_option: int) -> ScoredAnswer:
    """Score a multiple-choice submission against its stored answer key.

    Assumes the question was staged, which QuestionRepository.apply_review
    only allows once _validate_option_shape has confirmed correct_option is a
    valid index -- a staged MCQ always has one.
    """
    correct = selected_option == question.correct_option
    if correct:
        explanation = "Correct."
    else:
        correct_text = (
            question.options[question.correct_option]
            if question.options and question.correct_option is not None
            else None
        )
        explanation = f"The correct answer was: {correct_text}" if correct_text else None

    return ScoredAnswer(
        correct=correct,
        explanation=explanation,
        source_slide=question.source_slide,
    )


def classify_free_text(question: Question, free_text: str) -> ScoredAnswer:  # noqa: ARG001
    """Seam for Phase 5's semantic classifier. Owner: AI 1, Phase 5.

    A free-text submission is accepted and stored now so nothing is lost
    waiting for the classifier, but it cannot be scored without one: `correct`
    stays None (FeedbackResultPayload's documented "still classifying" state)
    rather than guessing right or wrong from no comparison at all.
    """
    return ScoredAnswer(
        correct=None,
        explanation="Your answer has been recorded.",
        source_slide=question.source_slide,
    )
