"""Question yield with lecturer evaluation (AI 1, #235). No model involved."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.content import Difficulty, QuestionType
from app.services.material_seams import DraftQuestion
from app.services.question_yield import (
    EDIT,
    REJECT,
    REJECTED_FIELDS,
    SHEET_FIELDS,
    USABLE,
    Judgement,
    consensus,
    judgement,
    missing_thresholds,
    page_kinds,
    question_row,
    read_rows,
    rejected_row,
    study_report,
    thresholds_agreed,
    wilson,
    write_rows,
)
from app.services.retrieval import RetrievedChunk
from scripts.evaluate_question_yield import (
    RecordingGenerator,
    collect,
    load_tags,
    load_thresholds,
)

THRESHOLDS = Path(__file__).parent / "eval" / "yield" / "thresholds.json"
AGREED = {
    "agreed_by": ["Luna", "Dr. Farhad"],
    "agreed_on": "2026-11-12",
    "min_usable_share_of_passed": 0.8,
    "max_incorrect_share_of_passed": 0.15,
    "min_usable_per_material": 2,
    "max_median_review_seconds": 90,
}
TAGS = {"diagram": [4], "formula": [4, 6]}


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


def marked(row, verdict, problem="", seconds="30"):
    return {**row, "verdict": verdict, "problem": problem, "seconds": seconds}


def study(judged, thresholds=AGREED):
    """Two lectures: four questions passed and two were rejected."""
    sheet = [
        question_row("m1-q01", "week3.pptx", draft("Q1", slide=4), TAGS),
        question_row("m1-q02", "week3.pptx", draft("Q2", slide=2), TAGS),
        question_row("m2-q01", "week4.pdf", draft("Q3", slide=1), {}),
        question_row("m2-q02", "week4.pdf", draft("Q4", slide=1), {}),
    ]
    rejected = [
        rejected_row(
            question_row("m1-x01", "week3.pptx", draft("Q5", slide=6), TAGS),
            ["no page or slide citation", "cites page 9, not among [1, 2]"],
        ),
        rejected_row(
            question_row("m2-x01", "week4.pdf", draft("Q6", slide=1), {}),
            ["excerpt not grounded in any chunk (best match 41)"],
        ),
    ]
    material = {"sha256": "ab" * 32, "pages": 10, "chunks": 12, "asked": 15, "calls": 3}
    run = {
        "started": "2026-11-12",
        "commit": "abc1234",
        "model": "qwen2.5:3b",
        "settings": {"questions_per_material": 15},
        "prompts": {"multiple choice (hash)": "0123456789ab"},
        "thresholds": thresholds,
        "materials": [
            {
                **material,
                "name": "week3.pptx",
                "drafts": 4,
                "passed": 2,
                "duplicates": 1,
                "empty_calls": 1,
                "tags": TAGS,
            },
            {
                **material,
                "name": "week4.pdf",
                "drafts": 3,
                "passed": 2,
                "duplicates": 0,
                "empty_calls": 0,
                "tags": {},
            },
        ],
    }
    rows = {row["id"]: row for row in sheet}
    by_judge = {
        name: [marked(rows.get(qid, {"id": qid}), *mark) for qid, mark in marks.items()]
        for name, marks in judged.items()
    }
    return study_report(run, sheet, rejected, by_judge)


def test_a_row_carries_the_question_its_answer_and_what_is_on_the_page():
    row = question_row("m1-q01", "week3.pptx", draft(), TAGS)
    assert row["correct_answer"] == "A ratio of odds"
    assert row["options"].count(" | ") == 3
    assert row["page_kinds"] == "diagram; formula"
    assert page_kinds(TAGS, 9) == []


def test_a_short_answer_row_carries_the_model_answer_and_key_points():
    free = DraftQuestion(
        type=QuestionType.FREE_TEXT,
        difficulty=Difficulty.EASY,
        prompt="Why freeze layers?",
        reference_answer="So their weights stay.",
        key_points=("weights stay", "less training"),
        source_slide=3,
    )
    row = question_row("m1-q01", "week3.pptx", free, {})
    assert (row["correct_answer"], row["key_points"]) == (
        "So their weights stay.",
        "weights stay | less training",
    )


def test_a_rejected_row_keeps_every_reason_and_its_kinds():
    row = rejected_row(
        question_row("m1-x01", "week3.pptx", draft(), TAGS),
        ["no page or slide citation", "expected 4 options, got 3"],
    )
    assert row["reasons"] == "no page or slide citation; expected 4 options, got 3"
    assert row["reason_kinds"] == "citation: missing or wrong page; format: options or answer"


def test_sheets_survive_being_written_and_read(tmp_path):
    rows = [question_row("m1-q01", "week3.pptx", draft('A "quoted", comma question'), TAGS)]
    write_rows(tmp_path / "sheet.csv", SHEET_FIELDS, rows)
    (back,) = read_rows(tmp_path / "sheet.csv")
    assert back["question"] == 'A "quoted", comma question'
    assert back["verdict"] == ""
    assert judgement(back) is None


def test_a_judgement_is_read_from_a_filled_in_row():
    row = question_row("m1-q01", "week3.pptx", draft(), TAGS)
    assert judgement(marked(row, "Usable ", "", "12")) == Judgement(USABLE, "", 12.0)
    assert judgement(marked(row, "edit", "unclear", "")) == Judgement(EDIT, "unclear", None)
    # A problem left on a usable question is ignored, not counted as a fault.
    assert judgement(marked(row, "usable", "unclear")).problem == ""


@pytest.mark.parametrize(
    ("verdict", "problem", "seconds"),
    [
        ("maybe", "", "10"),
        ("reject", "", "10"),
        ("edit", "typo", "10"),
        ("usable", "", "a while"),
        ("usable", "", "-5"),
    ],
)
def test_a_wrongly_filled_judgement_is_refused_not_dropped(verdict, problem, seconds):
    row = question_row("m1-q01", "week3.pptx", draft(), TAGS)
    with pytest.raises(ValueError, match="m1-q01"):
        judgement(marked(row, verdict, problem, seconds))


def test_the_strictest_judge_decides():
    assert consensus([USABLE, USABLE]) == USABLE
    assert consensus([USABLE, EDIT]) == EDIT
    assert consensus([EDIT, REJECT, USABLE]) == REJECT


def test_no_wrong_questions_in_a_small_sample_still_leaves_room_for_some():
    low, high = wilson(0, 12)
    assert low == 0
    assert 0.2 < high < 0.3
    low, high = wilson(6, 9)
    assert 0.35 < low < 0.36 and 0.87 < high < 0.88


def test_the_report_counts_yield_wrong_questions_faults_and_time():
    text = study(
        {
            "luna": {
                "m1-q01": ("usable", "", "20"),
                "m1-q02": ("edit", "unclear", "60"),
                "m2-q01": ("reject", "wrong_answer", "40"),
                "m2-q02": ("usable", "", "30"),
            },
            "farhad": {
                "m1-q01": ("usable", "", "10"),
                "m1-q02": ("usable", "", "30"),
                "m2-q01": ("reject", "several_right", "50"),
                "m2-q02": ("edit", "trivial", "70"),
            },
        }
    )
    assert "7 drafts, 4 passed the automated checks, 4 judged by all of 2 judge(s)" in text
    assert "| Passed and usable as they are | 1 of 4 (25%" in text
    assert "| Passed and usable after a correction | 2 of 4 (50%" in text
    assert "not in the material) | 1 of 4 (25%" in text
    assert "(usable either way, of all drafts) | 3 of 7 (43%" in text
    # By material, and by what the lecturer said is on the cited page.
    assert "| week3.pptx | 15 | 4 | 2 | 1 | 1 | 0 |" in text
    assert "| week4.pdf | 15 | 3 | 2 | 0 | 1 | 1 |" in text
    assert "| diagram | 1 | 1 | 1 | 0 |" in text
    assert "| formula | 2 | 1 | 1 | 0 |" in text
    assert "| text only | 4 | 3 | 2 | 1 |" in text
    # Both judges' faults on the rejected question are kept.
    assert "| the marked answer is wrong | 1 |" in text
    assert "| more than one option is right, or none is | 1 |" in text
    assert "| citation: missing or wrong page | 1 |" in text
    assert "1 more draft(s) passed but repeated a question" in text
    assert "1 of 6 model replies gave no drafts" in text
    assert "| farhad | 2 | 1 | 1 | 40 | 2.7 |" in text
    assert "same verdict on 2 of 4 questions" in text
    assert "about 52 seconds of review for each usable question" in text
    # 75% usable misses 80%, 25% wrong misses 15%, the thinner lecture gave
    # only one, and the median review took 35 seconds.
    assert "| at least 80% | 75% | **not met** |" in text
    assert "| at most 15% | 25% | **not met** |" in text
    assert "| at least 2 | 1 | **not met** |" in text
    assert "| at most 90 s | 35 s | met |" in text
    assert "agreed by Luna, Dr. Farhad on 2026-11-12" in text
    assert "Rehearsal" not in text and "Incomplete" not in text


def test_a_half_judged_run_says_so_and_claims_no_yield():
    text = study({"luna": {"m1-q01": ("usable", "", "20")}})
    assert "**Incomplete.** 3 of 4 questions have not been judged" in text
    assert "(usable either way, of all drafts) | - |" in text
    assert "a second, independent judge is still needed" in text
    assert "| at least 2 | - | not measured |" in text


def test_a_run_nobody_has_judged_still_reports_the_drafts():
    text = study({})
    assert "| Drafts that passed the automated checks | 4 of 7 (57%" in text
    assert "| Passed and usable either way | - |" in text
    assert "| at most 90 s | - | not measured |" in text


def test_a_run_without_agreed_thresholds_is_marked_a_rehearsal():
    text = study({}, {**AGREED, "agreed_by": []})
    assert "**Rehearsal.**" in text
    assert "**not agreed before the run**" in text


def test_a_mark_for_a_question_from_another_run_is_refused():
    with pytest.raises(ValueError, match="not in this run"):
        study({"luna": {"m9-q01": ("usable", "", "20")}})


def test_the_committed_thresholds_are_complete_but_not_yet_agreed(tmp_path):
    """The numbers are a proposal. The team fills in who agreed them and
    when; until then only a rehearsal runs."""
    thresholds = json.loads(THRESHOLDS.read_text())
    assert missing_thresholds(thresholds) == []
    if not thresholds_agreed(thresholds):
        with pytest.raises(SystemExit, match="not been agreed"):
            load_thresholds(THRESHOLDS, rehearsal=False)
        assert load_thresholds(THRESHOLDS, rehearsal=True) == thresholds


def test_thresholds_with_a_number_missing_are_refused(tmp_path):
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({**AGREED, "max_median_review_seconds": None}))
    with pytest.raises(SystemExit, match="max_median_review_seconds"):
        load_thresholds(path, rehearsal=True)


class FakeChatClient:
    """Replies in turn, as the model would to each call."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.chat = self

    @property
    def completions(self):
        return self

    async def create(self, model, messages, **kwargs):
        content = self._replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def chunk(index, page, text):
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), chunk_index=index, chunk_text=text, source_page=page, distance=0.1
    )


GOOD = (
    '{"prompt": "What happens to the base layers in transfer learning?",'
    ' "options": ["They are frozen", "Deleted", "Doubled", "Shuffled"],'
    ' "correct_option": 0, "topic": "T", "source_slide": 3,'
    ' "source_excerpt": "the base layers are frozen so their weights do not change"}'
)
INVENTED = (
    '{"prompt": "Which optimiser converges fastest?",'
    ' "options": ["Adam", "SGD", "RMSProp", "Adagrad"],'
    ' "correct_option": 0, "topic": "T", "source_slide": 9,'
    ' "source_excerpt": "Adam converges fastest"}'
)


async def test_a_run_keeps_what_the_upload_generator_kept_and_what_it_threw_away():
    chunks = [
        chunk(
            0,
            3,
            "Transfer learning reuses a network trained on a large dataset. "
            "The base layers are frozen so their weights do not change during training.",
        ),
        chunk(1, 4, "Fine-tuning then unfreezes the top layers and trains them slowly."),
    ]
    # Ten asked for is two calls: one good and one invented draft, then the
    # same good draft again.
    generator = RecordingGenerator(
        FakeChatClient(f"[{GOOD},{INVENTED}]", f"[{GOOD}]"), "test-model", count=10
    )
    passed, rejected, counts = await collect(
        generator, chunks, "week3.pptx", "m1", {"diagram": [3]}
    )
    assert [row["id"] for row in passed] == ["m1-q01"]
    assert passed[0]["page_kinds"] == "diagram"
    assert [row["id"] for row in rejected] == ["m1-x01"]
    assert "citation: missing or wrong page" in rejected[0]["reason_kinds"]
    assert set(REJECTED_FIELDS) <= set(rejected[0])
    assert (counts["calls"], counts["drafts"], counts["passed"]) == (2, 3, 1)
    assert (counts["duplicates"], counts["empty_calls"]) == (1, 0)
    assert counts["rejected_kinds"]["citation: missing or wrong page"] == 1


async def test_a_reply_that_cannot_be_read_counts_as_an_empty_call():
    chunks = [chunk(0, 3, "The base layers are frozen so their weights do not change.")]
    generator = RecordingGenerator(FakeChatClient("not json at all"), "test-model", count=5)
    passed, rejected, counts = await collect(generator, chunks, "week3.pptx", "m1", {})
    assert (passed, rejected) == ([], [])
    assert (counts["calls"], counts["empty_calls"], counts["drafts"]) == (1, 1, 0)


def test_a_tags_file_may_cover_more_lectures_than_are_run(tmp_path, capsys):
    path = tmp_path / "tags.json"
    path.write_text(json.dumps({"week3.pptx": {"diagram": [4]}, "week9.pdf": {"formula": [2]}}))
    assert load_tags(path, ["week3.pptx", "renamed.pdf"]) == {"week3.pptx": {"diagram": [4]}}
    printed = capsys.readouterr().out
    assert "No tags" in printed and "renamed.pdf" in printed


def test_the_committed_practice_tags_name_real_pages():
    tags = json.loads((THRESHOLDS.parent / "pilot1_tags.json").read_text())
    for lecture, kinds in tags.items():
        for kind, pages in kinds.items():
            assert pages == sorted(set(pages)) and pages[0] >= 1, (lecture, kind)
