"""Question grounding for the AI evaluation report (Phase 8, AI 1, #73)."""

from app.schemas.content import Difficulty, QuestionType
from app.services.grounding_evaluation import (
    OTHER,
    GroundingTally,
    grounding_precision,
    reason_kind,
    summary_markdown,
    write_accepted,
)
from app.services.material_seams import DraftQuestion


def draft(prompt="What is an odds ratio?", slide=4):
    return DraftQuestion(
        type=QuestionType.MCQ,
        difficulty=Difficulty.EASY,
        prompt=prompt,
        options=("A ratio of odds", "A probability", "A mean", "A slope"),
        correct_option=0,
        source_slide=slide,
        source_excerpt="the odds ratio compares the odds",
    )


def test_each_rejection_reason_has_a_kind():
    assert reason_kind("no page or slide citation") == "citation: missing or wrong page"
    assert reason_kind("cites page 9, not among [1, 2]") == "citation: missing or wrong page"
    assert reason_kind("excerpt not grounded in any chunk (best match 41)") == (
        "excerpt not found on the page"
    )
    assert reason_kind("correct answer has little overlap with the cited excerpt (score 10)") == (
        "answer not supported by the excerpt"
    )
    assert reason_kind("question has little overlap with the cited material (score 5)") == (
        "question off the cited page"
    )
    assert reason_kind("expected 4 options, got 3") == "format: options or answer"
    assert reason_kind("the draft itself contains instructions") == (
        "safety: instructions or links"
    )
    assert reason_kind("something new") == OTHER


def test_the_tally_counts_replies_drafts_and_reasons():
    tally = GroundingTally()
    tally.add_reply([(draft(), []), (draft("Q2"), ["no page or slide citation"])])
    tally.add_reply(None)
    tally.add_reply(
        [(draft("Q3"), ["excerpt not grounded in any chunk (best match 40)", "cites page 9"])]
    )
    assert (tally.replies, tally.unreadable) == (3, 1)
    assert (tally.drafts, len(tally.accepted), tally.rejected) == (3, 1, 2)
    assert tally.acceptance_rate == 1 / 3
    # Two citation reasons on one draft count that draft once.
    assert tally.kinds["citation: missing or wrong page"] == 2
    assert tally.kinds["excerpt not found on the page"] == 1


def test_no_drafts_has_no_rate():
    tally = GroundingTally()
    tally.add_reply(None)
    assert tally.acceptance_rate is None
    assert "| Acceptance rate | - |" in summary_markdown(tally, "m", "lecture.pptx")


def test_accepted_questions_are_written_for_a_person_to_judge(tmp_path):
    path = tmp_path / "accepted.csv"
    write_accepted(path, [draft(), draft("Q2", slide=7)])
    text = path.read_text()
    assert "g01,mcq,What is an odds ratio?" in text
    assert "A ratio of odds" in text
    assert text.splitlines()[0].endswith("grounded_luna,notes")


def test_grounding_precision_counts_only_judged_rows(tmp_path):
    path = tmp_path / "accepted.csv"
    write_accepted(path, [draft(), draft("Q2"), draft("Q3")])
    rows = path.read_text().splitlines()
    rows[1] = rows[1].replace(",,", ",yes,", 1)
    rows[2] = rows[2].replace(",,", ",no,", 1)
    path.write_text("\n".join(rows) + "\n")
    assert grounding_precision(path) == (1, 2)


def test_every_reason_the_generator_writes_has_a_kind():
    import re
    from pathlib import Path

    import app.services.generation as generation

    source = Path(generation.__file__).read_text()
    reasons = re.findall(r'reasons\.append\(\s*f?"([^"]+)"', source)
    assert len(reasons) > 15
    assert [r for r in reasons if reason_kind(r) == OTHER] == []


def test_free_text_answer_reasons_count_as_unsupported_answers():
    for reason in (
        "reference answer has little overlap with the cited excerpt (score 10)",
        "key point 2 has little overlap with the cited excerpt (score 0)",
    ):
        assert reason_kind(reason) == "answer not supported by the excerpt"
