"""OCR accuracy arithmetic for the AI evaluation report (Phase 8, AI 1, #73)."""

import pytest

from app.services.ocr_evaluation import OcrScore, markdown_table, normalise


def test_normalise_ignores_case_punctuation_and_spacing():
    assert normalise("Goal:Enable  machines, NOW!") == "goal enable machines now"
    assert normalise("vision_model  ∼80%") == "vision model 80"


def test_a_perfect_read_has_no_errors():
    score = OcrScore()
    score.add("The odds ratio.", "the ODDS ratio", seconds=0.5, was_read=True)
    assert (score.cer, score.wer, score.word_recall) == (0.0, 0.0, 1.0)


def test_one_wrong_letter_is_one_character_and_one_word_error():
    score = OcrScore()
    score.add("odds ratio", "odds rafio", seconds=0, was_read=True)
    assert score.cer == pytest.approx(1 / 9)  # 9 letters, spaces not counted
    assert score.wer == pytest.approx(1 / 2)
    assert score.word_recall == pytest.approx(1 / 2)


def test_extra_text_counts_against_wer_but_not_word_recall():
    score = OcrScore()
    score.add("logistic regression", "logistic regression university logo", 0, True)
    assert score.wer == pytest.approx(2 / 2)
    assert score.word_recall == 1.0


def test_word_recall_ignores_order_and_counts_repeats_once_each():
    score = OcrScore()
    score.add("odds odds ratio", "ratio odds", 0, True)
    assert score.word_recall == pytest.approx(2 / 3)


def test_pages_are_pooled_by_length():
    score = OcrScore()
    score.add("a b c d e f g h", "a b c d e f g h", 1.0, True)
    score.add("x y", "", 3.0, False)
    assert score.wer == pytest.approx(2 / 10)
    assert (score.pages, score.pages_read) == (2, 1)
    assert score.seconds_per_page == 2.0


def test_the_table_has_a_row_per_document_and_scan():
    score = OcrScore()
    score.add("odds ratio", "odds ratio", 0.4, True)
    table = markdown_table([("Slides", "clean", score)])
    assert "| Slides | clean | 1 of 1 | 100.0% | 0.0% | 0.0% | 0.4 |" in table
